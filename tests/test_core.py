"""Цепочка моделей, кэш, учёт, бюджет и пачки задач."""

from __future__ import annotations

import asyncio
import logging
import time

import conftest as fakes
import pytest
from conftest import FakeCompletion, response
from pydantic import BaseModel

from llmkit import AllModelsFailed, LlmKit, Task
from llmkit import keys as keys_mod


def kit(script=None, **kwargs) -> tuple[LlmKit, FakeCompletion]:
    completion = script if isinstance(script, FakeCompletion) else FakeCompletion(script)
    return LlmKit(completion=completion, **kwargs), completion


async def test_text_answer_and_usage_row():
    instance, fake = kit([response("привет")])
    answer = await instance.ask(Task(user="вопрос", tags={"tool": "t"}))
    assert answer.data == "привет"
    assert answer.source == "llm"
    assert answer.model == "a/m1"
    assert (answer.prompt_tokens, answer.completion_tokens) == (10, 5)
    # Цена из конфига: 10 токенов по $1/1M + 5 по $2/1M.
    assert answer.cost_usd == pytest.approx((10 * 1.0 + 5 * 2.0) / 1_000_000)
    assert answer.cost_known
    assert fake.calls[0]["model"] == "openai/m1"
    assert fake.calls[0]["api_base"] == "http://localhost:11111/v1"
    rows = instance.usage.report(("tool",))
    assert rows[0].keys == {"tool": "t"} and rows[0].calls == 1 and rows[0].failed == 0


async def test_timeout_retries_then_next_model(slept):
    instance, fake = kit({"openai/m1": [fakes.Timeout("долго")], "openai/m2": [response("со второй")]})
    answer = await instance.ask(Task(user="вопрос"))
    assert answer.data == "со второй"
    assert answer.model == "b/m2"
    # retry.timeout = 1 → два вызова первой модели, затем вторая.
    assert fake.models() == ["openai/m1", "openai/m1", "openai/m2"]
    assert [a.error_type for a in answer.attempts] == ["timeout", "timeout", None]
    assert slept == []  # у timeout паузы нет
    assert instance.stats.fallbacks == 1


async def test_rate_limit_backoff(slept):
    instance, fake = kit({"openai/m1": [fakes.RateLimitError("429")], "openai/m2": [response()]})
    await instance.ask(Task(user="вопрос"))
    assert fake.models().count("openai/m1") == 3  # исходный вызов + retry.rate_limit
    assert slept == [2.0, 4.0]


async def test_server_error_retries(slept):
    instance, fake = kit({"openai/m1": [fakes.ServiceUnavailableError("503")], "openai/m2": [response()]})
    await instance.ask(Task(user="вопрос"))
    assert fake.models().count("openai/m1") == 3
    assert slept == [2.0, 4.0]


@pytest.mark.parametrize(
    ("exc", "error_type"),
    [
        (fakes.InstructorRetryException("схема"), "invalid_output"),
        (fakes.ContentPolicyViolationError("нельзя"), "refusal"),
        (fakes.ContextWindowExceededError("длинно"), "context_length"),
        (fakes.AuthenticationError("ключ"), "auth"),
        (fakes.BadRequestError("аргументы"), "bad_request"),
    ],
)
async def test_non_retryable_errors_go_to_next_model(exc, error_type, slept):
    instance, fake = kit({"openai/m1": [exc], "openai/m2": [response("вторая")]})
    answer = await instance.ask(Task(user="вопрос"))
    assert answer.data == "вторая"
    assert fake.models() == ["openai/m1", "openai/m2"]  # повторов на первой нет
    assert answer.attempts[0].error_type == error_type


async def test_empty_answer_is_invalid_output():
    instance, _ = kit({"openai/m1": [response("   ")], "openai/m2": [response("вторая")]})
    answer = await instance.ask(Task(user="вопрос"))
    assert answer.attempts[0].error_type == "invalid_output"
    assert answer.data == "вторая"


async def test_content_filter_finish_reason_is_refusal():
    instance, _ = kit(
        {
            "openai/m1": [response("текст", finish_reason="content_filter")],
            "openai/m2": [response("вторая")],
        }
    )
    answer = await instance.ask(Task(user="вопрос"))
    assert answer.attempts[0].error_type == "refusal"


async def test_json_schema_parse_retries_on_same_model(slept):
    schema = {"type": "object", "properties": {"x": {"type": "integer"}}}
    instance, fake = kit({"openai/m1": [response("не json"), response('{"x": 1}')], "openai/m2": [response("{}")]})
    answer = await instance.ask(Task(user="вопрос", schema=schema))
    # Первая попытка не разобралась, вторая — на той же модели.
    assert fake.models() == ["openai/m1", "openai/m1"]
    assert answer.data == {"x": 1}
    assert fake.calls[0]["response_format"]["json_schema"]["schema"] == schema


async def test_missing_key_is_auth_error_and_skips_model(monkeypatch):
    monkeypatch.delenv("TEST_A_KEY")
    monkeypatch.setattr(keys_mod, "from_keychain", lambda provider: None)
    instance, fake = kit({"openai/m2": [response("вторая")]})
    answer = await instance.ask(Task(user="вопрос"))
    assert answer.attempts[0].error_type == "auth"
    assert fake.models() == ["openai/m2"]  # к модели без ключа не ходили


async def test_all_models_failed_without_default():
    instance, _ = kit([fakes.BadRequestError("всё плохо")])
    with pytest.raises(AllModelsFailed) as info:
        await instance.ask(Task(user="вопрос"))
    assert len(info.value.attempts) == 2
    assert instance.stats.failed == 1


async def test_default_returned_instead_of_error():
    instance, _ = kit([fakes.BadRequestError("всё плохо")])
    answer = await instance.ask(Task(user="вопрос", default={"пусто": True}))
    assert answer.source == "default" and answer.data == {"пусто": True}
    assert answer.ok is False and answer.error


async def test_generate_returns_none_on_total_failure():
    instance, _ = kit([fakes.BadRequestError("всё плохо")])
    assert await instance.generate("вопрос") is None


async def test_generate_returns_text():
    instance, _ = kit([response("готово")])
    assert await instance.generate("вопрос", system="ты бот") == "готово"


async def test_cache_hit_and_key_depends_on_model():
    instance, fake = kit([response("из сети")])
    first = await instance.ask(Task(user="вопрос"))
    second = await instance.ask(Task(user="вопрос"))
    assert first.source == "llm" and second.source == "cache"
    assert second.data == "из сети"
    assert len(fake.calls) == 1
    assert instance.stats.cached == 1
    # Та же задача на другой модели кэш не переиспользует.
    third = await instance.ask(Task(user="вопрос", chain=["b/m2"]))
    assert third.source == "llm" and len(fake.calls) == 2
    rows = instance.usage.report()
    assert rows[0].calls == 3 and rows[0].cached == 1


async def test_cache_can_be_disabled_per_task():
    instance, fake = kit([response("ответ")])
    await instance.ask(Task(user="вопрос"))
    await instance.ask(Task(user="вопрос", cache=False))
    assert len(fake.calls) == 2


async def test_usage_has_a_row_per_attempt(slept):
    instance, _ = kit({"openai/m1": [fakes.Timeout("долго")], "openai/m2": [response()]})
    await instance.ask(Task(user="вопрос", tags={"tool": "t", "niche": "ved"}, id="задача-1"))
    rows = instance.usage.report(("tool", "niche"))
    assert len(rows) == 1
    assert rows[0].calls == 3 and rows[0].failed == 2
    total = instance.usage.total()
    assert total.calls == 3


async def test_report_groups_by_tags():
    instance, _ = kit([response()])
    await instance.ask(Task(user="раз", tags={"tool": "one"}))
    await instance.ask(Task(user="два", tags={"tool": "two"}))
    await instance.ask(Task(user="три", tags={"tool": "two"}))
    rows = {row.keys["tool"]: row for row in instance.usage.report(("tool",))}
    assert rows["two"].calls == 2 and rows["one"].calls == 1


async def test_budget_warning_logged_once_per_process(caplog):
    instance, _ = kit([response()])
    instance.config.budget.daily_usd = 0.0
    instance.config.budget.tags = {"tool=t": 0.0}
    instance.usage.record(model="a/m1", provider="a", status="ok", cost_usd=1.0, tags={"tool": "t"})
    with caplog.at_level(logging.WARNING, logger="llmkit.core"):
        first = await instance.ask(Task(user="раз", tags={"tool": "t"}))
        second = await instance.ask(Task(user="два", tags={"tool": "t"}))
    assert len(first.warnings) == 2 and len(second.warnings) == 2  # дневной и по метке
    budget_records = [r for r in caplog.records if "бюджет" in r.getMessage()]
    assert len(budget_records) == 2  # по одной строке на каждый бюджет за процесс


async def test_unknown_price_marks_cost_unknown():
    instance, _ = kit([response()])
    answer = await instance.ask(Task(user="вопрос", chain=["b/m2"]))  # цен для b в конфиге нет
    assert answer.cost_usd == 0.0 and answer.cost_known is False


async def test_ask_many_keeps_order_and_limits_concurrency():
    fake = FakeCompletion([lambda **kw: response(kw["messages"][-1]["content"])], delay=0.01)
    instance, _ = kit(fake)
    tasks = [Task(user=f"вопрос-{i}") for i in range(6)]
    progress: list[int] = []
    answers = await instance.ask_many(tasks, on_progress=lambda done, total, answer: progress.append(done))
    assert [a.data for a in answers] == [f"вопрос-{i}" for i in range(6)]
    assert fake.max_running <= 2  # defaults.concurrency из тестового конфига
    assert progress == [1, 2, 3, 4, 5, 6]


async def test_ask_many_does_not_break_on_failure():
    fake = FakeCompletion(
        [lambda **kw: fakes.BadRequestError("нет") if "плохой" in kw["messages"][-1]["content"] else response("ок")]
    )
    instance, _ = kit(fake)
    answers = await instance.ask_many([Task(user="плохой"), Task(user="хороший")])
    assert answers[0].source == "default" and answers[0].data is None and answers[0].error
    assert answers[1].data == "ок"


async def test_ask_many_can_raise():
    instance, _ = kit([fakes.BadRequestError("нет")])
    with pytest.raises(AllModelsFailed):
        await instance.ask_many([Task(user="плохой")], raise_on_error=True)


async def test_stats_accumulate(slept):
    instance, _ = kit({"openai/m1": [fakes.Timeout("долго")], "openai/m2": [response()]})
    await instance.ask(Task(user="раз"))
    await instance.ask(Task(user="раз"))  # второй раз из кэша
    stats = instance.stats
    # Первая задача дошла до второй модели, вторая взяла её же из кэша — два перехода.
    assert stats.calls == 2 and stats.cached == 1 and stats.fallbacks == 2
    assert stats.by_model["b/m2"] == 2 and stats.seconds >= 0


async def test_explicit_chain_overrides_level():
    instance, fake = kit([response()])
    await instance.ask(Task(user="вопрос", chain=["b/m2"]))
    assert fake.models() == ["openai/m2"]


async def test_kit_level_override_applies():
    instance, fake = kit([response()], level="solo")
    answer = await instance.ask(Task(user="вопрос"))
    assert answer.model == "a/m1" and fake.models() == ["openai/m1"]


async def test_sync_wrappers_work_from_running_loop():
    """ask_sync вызван внутри работающего loop — работа уходит в отдельный поток."""
    instance, _ = kit([response("синхронно")])
    assert asyncio.get_running_loop().is_running()
    assert instance.ask_sync(Task(user="вопрос")).data == "синхронно"
    assert instance.generate_sync("другой вопрос") == "синхронно"


def test_sync_wrappers_without_loop():
    instance, _ = kit([response("синхронно")])
    assert instance.ask_sync(Task(user="вопрос")).data == "синхронно"
    assert instance.generate_sync("другой вопрос") == "синхронно"
    assert [a.data for a in instance.ask_many_sync([Task(user="третий")])] == ["синхронно"]
    instance.close()


# --- правки по итогам ревью ---


class Shape(BaseModel):
    name: str


class FakeInstructorClient:
    """Клиент Instructor для тестов: отдаёт заготовленный шаг."""

    def __init__(self, steps) -> None:
        self.steps = list(steps)
        self.calls: list[dict] = []
        self.chat = type("chat", (), {"completions": self})()

    async def create_with_completion(self, **kwargs):
        self.calls.append(kwargs)
        step = self.steps[min(len(self.calls) - 1, len(self.steps) - 1)]
        if isinstance(step, BaseException):
            raise step
        return step


def structured_kit(steps):
    client = FakeInstructorClient(steps)
    instance = LlmKit(completion=FakeCompletion(), instructor_factory=lambda completion, mode: client)
    return instance, client


async def test_structured_path_returns_pydantic_object():
    instance, client = structured_kit([(Shape(name="куб"), response())])
    answer = await instance.ask(Task(user="вопрос", schema=Shape))
    assert answer.data == Shape(name="куб") and answer.source == "llm"
    assert client.calls[0]["response_model"] is Shape
    # Тот же ответ из кэша восстанавливается как pydantic-объект.
    again = await instance.ask(Task(user="вопрос", schema=Shape))
    assert again.source == "cache" and again.data == Shape(name="куб")


async def test_instructor_error_keeps_provider_error_type(slept):
    wrapped = fakes.InstructorRetryException("схема не собралась")
    wrapped.__cause__ = fakes.RateLimitError("429")
    instance, client = structured_kit([wrapped, (Shape(name="куб"), response())])
    answer = await instance.ask(Task(user="вопрос", schema=Shape, chain=["a/m1"]))
    # rate_limit, а не invalid_output: значит был повтор с паузой.
    assert answer.attempts[0].error_type == "rate_limit"
    assert slept == [2.0] and len(client.calls) == 2


async def test_cache_key_separates_same_model_on_different_providers():
    instance, fake = kit([response("от a"), response("от b")])
    first = await instance.ask(Task(user="вопрос", chain=["a/одна-модель"]))
    second = await instance.ask(Task(user="вопрос", chain=["b/одна-модель"]))
    # Одинаковое имя модели у разных провайдеров — разные ключи кэша.
    assert first.data == "от a" and second.data == "от b"
    assert len(fake.calls) == 2


async def test_cache_hit_anywhere_in_chain_skips_the_network():
    instance, fake = kit({"openai/m1": [fakes.BadRequestError("нет")], "openai/m2": [response("от второй")]})
    first = await instance.ask(Task(user="вопрос"))
    assert first.model == "b/m2" and len(fake.calls) == 2
    # Повтор: ответ второй модели лежит в кэше — первая модель не вызывается.
    second = await instance.ask(Task(user="вопрос"))
    assert second.source == "cache" and second.model == "b/m2"
    assert len(fake.calls) == 2


async def test_cache_hit_works_without_provider_key(monkeypatch):
    instance, fake = kit([response("закэшировано")])
    await instance.ask(Task(user="вопрос"))
    monkeypatch.delenv("TEST_A_KEY")
    monkeypatch.setattr(keys_mod, "from_keychain", lambda provider: None)
    answer = await instance.ask(Task(user="вопрос"))
    assert answer.source == "cache" and len(fake.calls) == 1


async def test_cache_row_is_recorded_as_first_attempt():
    instance, _ = kit([response()])
    await instance.ask(Task(user="вопрос"))
    await instance.ask(Task(user="вопрос"))
    with instance.usage._connect() as connection:
        rows = connection.execute("SELECT status, attempt FROM calls ORDER BY id").fetchall()
    assert rows == [("ok", 0), ("cache", 0)]


async def test_unknown_exception_is_not_masked_as_provider_error():
    instance, _ = kit([TypeError("баг в нашем коде")])
    with pytest.raises(TypeError):
        await instance.ask(Task(user="вопрос"))


async def test_failed_task_counts_in_stats_and_keeps_latency():
    instance, _ = kit([fakes.BadRequestError("нет")])
    with pytest.raises(AllModelsFailed) as info:
        await instance.ask(Task(user="вопрос"))
    assert instance.stats.calls == 1 and instance.stats.failed == 1
    answer = info.value.answer
    assert answer is not None and answer.source == "default" and answer.latency_ms >= 0
    assert info.value.error_type == "bad_request"


async def test_all_models_failed_error_type_is_none_when_mixed(slept):
    instance, _ = kit({"openai/m1": [fakes.Timeout("долго")], "openai/m2": [fakes.BadRequestError("нет")]})
    with pytest.raises(AllModelsFailed) as info:
        await instance.ask(Task(user="вопрос"))
    assert info.value.error_type is None


async def test_ask_many_failure_answer_has_metadata():
    instance, _ = kit([fakes.BadRequestError("нет")])
    answers = await instance.ask_many([Task(user="плохой", id="задача-1")])
    assert answers[0].source == "default" and answers[0].task_id == "задача-1"
    assert answers[0].attempts and answers[0].latency_ms >= 0
    assert instance.stats.calls == 1 and instance.stats.failed == 1


async def test_raise_on_error_cancels_remaining_tasks():
    calls: list[str] = []
    finished: list[str] = []

    async def completion(**kwargs):
        content = kwargs["messages"][-1]["content"]
        calls.append(content)
        if "плохой" in content:
            raise fakes.BadRequestError("нет")
        await asyncio.sleep(0.2)
        finished.append(content)
        return response("ок")

    instance = LlmKit(completion=completion, concurrency=4)
    tasks = [Task(user="плохой"), *[Task(user=f"хороший-{i}") for i in range(3)]]
    started = time.perf_counter()
    with pytest.raises(AllModelsFailed):
        await instance.ask_many(tasks, raise_on_error=True)
    assert time.perf_counter() - started < 0.2  # спящих задач не дожидались
    await asyncio.sleep(0.25)
    assert finished == []  # отменённые задачи в сеть больше не сходили
    # Упавшая задача прошла оба звена цепочки, остальные отменены на первом же await.
    assert calls.count("плохой") == 2 and len(calls) < 8


async def test_on_progress_error_does_not_break_the_batch(caplog):
    instance, _ = kit([response()])

    def broken(done, total, answer):
        raise RuntimeError("колбэк сломался")

    with caplog.at_level(logging.ERROR, logger="llmkit.core"):
        answers = await instance.ask_many([Task(user="раз"), Task(user="два")], on_progress=broken)
    assert len(answers) == 2 and all(a.ok for a in answers)
    assert any("on_progress" in record.getMessage() for record in caplog.records)


async def test_budget_warning_is_not_repeated_per_model_in_chain(slept):
    instance, _ = kit({"openai/m1": [fakes.Timeout("долго")], "openai/m2": [response()]})
    instance.config.budget.daily_usd = 0.0
    instance.usage.record(model="a/m1", provider="a", status="ok", cost_usd=1.0)
    answer = await instance.ask(Task(user="вопрос"))
    assert len(answer.warnings) == 1  # одно предупреждение на задачу, не на модель


async def test_api_key_is_masked_in_errors():
    instance, _ = kit([fakes.BadRequestError("ключ ключ-a протух")])
    answer = await instance.ask(Task(user="вопрос", default="нет"))
    assert "ключ-a" not in (answer.attempts[0].error or "")
    assert "***" in (answer.attempts[0].error or "")


async def test_generate_returns_default_when_given():
    instance, _ = kit([fakes.BadRequestError("нет")])
    assert await instance.generate("вопрос", default="запасной ответ") == "запасной ответ"
    assert await instance.generate("вопрос") is None
