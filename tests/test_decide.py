"""LlmKit.decide и транспорт эндпоинта решений — без сети."""

from __future__ import annotations

import json
import sqlite3

import httpx
import pytest

from llmkit import AllModelsFailed, ConfigError, LlmKit
from llmkit.transports import decisions
from llmkit.transports._common import SubscriptionEmpty, SubscriptionServerError
from llmkit.usage import Usage

QUESTIONS = {
    "is_urgent": {
        "type": "noul",
        "instructions": "Does this message convey urgency?",
        "criteria": {"true": "Explicitly time-sensitive", "false": "No urgency expressed"},
    }
}

ANSWERS = {"is_urgent": {"type": "noul", "noul": 0.95}}


def body(*, cost: float | None = 1.7934e-05) -> dict:
    """Ответ в форме живого вызова 2026-09-28."""
    usage = {"input_tokens": 427, "output_tokens": 73}
    if cost is not None:
        usage["cost"] = cost
    return {
        "model": "typesafe/jev-1.13-20260917",
        "answers": ANSWERS,
        "usage": usage,
        "id": "gen-dec-1",
        "provider": "TypeSafe",
    }


class FakeDecisions:
    """Подменяет `decisions.adecide`: сценарий из исключений и ответов, последний повторяется."""

    def __init__(self, *steps) -> None:
        self.steps = list(steps) or [body()]
        self.calls: list[dict] = []

    async def __call__(self, **kwargs):
        self.calls.append(kwargs)
        step = self.steps[min(len(self.calls) - 1, len(self.steps) - 1)]
        if isinstance(step, BaseException):
            raise step
        return step


# Цепочка decide — из routing: уровня `decide` больше нет.
DECIDE_ROUTING = {
    "providers": {
        "openrouter": {"protocol": "openrouter", "key_env": "LLM_OPENROUTER_API_KEY"},
        "a": {"protocol": "openai_compatible", "base_url": "http://localhost:11111/v1", "key_env": "TEST_A_KEY"},
    },
    "chain": ["openrouter/~typesafe/jev-latest"],
}


@pytest.fixture(autouse=True)
def openrouter_key(monkeypatch):
    monkeypatch.setenv("LLM_OPENROUTER_API_KEY", "ключ-or")


def usage_rows(kit: LlmKit) -> list[tuple]:
    with sqlite3.connect(kit.config.usage_path()) as connection:
        return connection.execute(
            "SELECT model, status, level, attempt, prompt_tokens, completion_tokens, cost_usd, served_model"
            " FROM llmkit_calls ORDER BY id"
        ).fetchall()


async def test_decide_returns_answers_cost_and_served_model():
    fake = FakeDecisions()
    kit = LlmKit(routing=DECIDE_ROUTING, decisions=fake, tags={"tool": "stand"})

    answer = await kit.decide("Help! Payouts failing.", QUESTIONS)

    assert answer.data == ANSWERS
    assert answer.source == "llm"
    assert answer.model == "openrouter/~typesafe/jev-latest"
    assert answer.served_model == "typesafe/jev-1.13-20260917"
    assert answer.cost_usd == pytest.approx(1.7934e-05)
    assert (answer.prompt_tokens, answer.completion_tokens) == (427, 73)
    assert fake.calls[0]["model"] == "~typesafe/jev-latest"
    assert fake.calls[0]["api_key"] == "ключ-or"
    assert fake.calls[0]["questions"] == QUESTIONS
    assert usage_rows(kit) == [
        (
            "openrouter/~typesafe/jev-latest",
            "ok",
            None,  # уровней нет: колонка level больше не заполняется
            0,
            427,
            73,
            pytest.approx(1.7934e-05),
            "typesafe/jev-1.13-20260917",
        )
    ]


async def test_decide_retries_503_on_same_model(slept):
    fake = FakeDecisions(SubscriptionServerError("HTTP 503: busy"), body())
    kit = LlmKit(routing=DECIDE_ROUTING, decisions=fake)

    answer = await kit.decide("s", QUESTIONS)

    assert answer.ok
    assert len(fake.calls) == 2
    assert slept == [2.0]
    assert [row[1] for row in usage_rows(kit)] == ["failed", "ok"]


async def test_decide_all_failed_raises_or_default(slept):
    kit = LlmKit(routing=DECIDE_ROUTING, decisions=FakeDecisions(SubscriptionServerError("HTTP 503")))
    with pytest.raises(AllModelsFailed):
        await kit.decide("s", QUESTIONS)

    answer = await kit.decide("s", QUESTIONS, default={})
    assert answer.source == "default"
    assert answer.data == {}


async def test_decide_cost_from_routing_when_response_has_none():
    routing = {**DECIDE_ROUTING, "prices": {"openrouter/~typesafe/jev-latest": {"input": 0.042, "output": 0}}}
    kit = LlmKit(routing=routing, decisions=FakeDecisions(body(cost=None)))

    answer = await kit.decide("s", QUESTIONS)

    assert answer.cost_known and answer.cost_source == "routing"
    assert answer.cost_usd == pytest.approx(427 * 0.042 / 1_000_000)


async def test_decide_rejects_non_openrouter_models():
    kit = LlmKit(routing=DECIDE_ROUTING, decisions=FakeDecisions())
    with pytest.raises(ConfigError, match="OpenRouter"):
        await kit.decide("s", QUESTIONS, chain=["a/m1"])


def test_decide_sync():
    kit = LlmKit(routing=DECIDE_ROUTING, decisions=FakeDecisions())
    assert kit.decide_sync("s", QUESTIONS).data == ANSWERS


def test_cli_decide_json(monkeypatch, tmp_path):
    from typer.testing import CliRunner

    from llmkit.cli import runtime
    from llmkit.cli.main import app

    fake = FakeDecisions()
    monkeypatch.setattr(runtime, "build_kit", lambda **kwargs: LlmKit(decisions=fake, **kwargs))
    routing = json.dumps(DECIDE_ROUTING)
    questions = tmp_path / "q.json"
    questions.write_text(json.dumps(QUESTIONS), encoding="utf-8")

    result = CliRunner().invoke(
        app, ["decide", "Payouts failing", "--questions", str(questions), "--routing", routing, "--json"]
    )

    assert result.exit_code == 0, result.output
    envelope = json.loads(result.stdout)
    assert envelope["data"] == ANSWERS
    assert envelope["served_model"] == "typesafe/jev-1.13-20260917"
    assert fake.calls[0]["state"] == "Payouts failing"


def test_cli_decide_rejects_non_openrouter_model(monkeypatch, tmp_path):
    from typer.testing import CliRunner

    from llmkit.cli import runtime
    from llmkit.cli.main import app

    monkeypatch.setattr(runtime, "build_kit", lambda **kwargs: LlmKit(decisions=FakeDecisions(), **kwargs))
    questions = tmp_path / "q.json"
    questions.write_text(json.dumps(QUESTIONS), encoding="utf-8")

    providers_only = json.dumps({"providers": DECIDE_ROUTING["providers"]})
    result = CliRunner().invoke(
        app, ["decide", "s", "-q", str(questions), "--routing", providers_only, "--model", "a/m1"]
    )

    assert result.exit_code == 2


def test_old_usage_db_gets_served_model_column(tmp_path):
    path = tmp_path / "old.sqlite"
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE calls (id INTEGER PRIMARY KEY, ts REAL, task_id TEXT, tags TEXT, level TEXT, model TEXT,"
            " provider TEXT, status TEXT, error_type TEXT, attempt INTEGER, prompt_tokens INTEGER,"
            " completion_tokens INTEGER, cost_usd REAL, cost_known INTEGER, latency_ms INTEGER, pid INTEGER)"
        )

    Usage(path).record(model="openrouter/x", provider="openrouter", status="ok", served_model="x-1")

    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT served_model FROM llmkit_calls").fetchall() == [("x-1",)]


# --- транспорт ---


@pytest.fixture
def mock_http(monkeypatch):
    """httpx.AsyncClient с подменённым транспортом; `seen` — отправленные запросы."""
    seen: list[httpx.Request] = []
    handler_box: dict = {}
    real = httpx.AsyncClient

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler_box["reply"](request)

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))

    def reply_with(fn):
        handler_box["reply"] = fn
        return seen

    return reply_with


async def test_transport_posts_and_returns_body(mock_http):
    seen = mock_http(lambda request: httpx.Response(200, json=body()))

    data = await decisions.adecide(model="~typesafe/jev-latest", state="s", questions=QUESTIONS, timeout=5, api_key="k")

    assert data["answers"] == ANSWERS
    assert str(seen[0].url) == decisions.URL
    assert seen[0].headers["Authorization"] == "Bearer k"
    assert json.loads(seen[0].content) == {"model": "~typesafe/jev-latest", "state": "s", "questions": QUESTIONS}


async def test_transport_503_is_server_error(mock_http):
    mock_http(lambda request: httpx.Response(503, text="busy", headers={"Retry-After": "3"}))
    with pytest.raises(SubscriptionServerError) as info:
        await decisions.adecide(model="m", state="s", questions=QUESTIONS, timeout=5)
    assert info.value.headers.get("retry-after") == "3"


async def test_transport_without_answers_is_empty(mock_http):
    mock_http(lambda request: httpx.Response(200, json={"model": "m"}))
    with pytest.raises(SubscriptionEmpty):
        await decisions.adecide(model="m", state="s", questions=QUESTIONS, timeout=5)
