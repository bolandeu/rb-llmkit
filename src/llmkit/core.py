"""LlmKit: ask / generate / ask_many и sync-обёртки (раздел 5)."""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from . import cache as cache_mod
from . import chain as chain_mod
from . import config as config_mod
from . import providers as providers_mod
from .cache import Cache
from .config import Config
from .errors import AllModelsFailed, ConfigError, KeyMissing, LlmKitError
from .usage import Usage

log = logging.getLogger("llmkit.core")

# Модели, для которых цена неизвестна: предупреждаем один раз за процесс,
# иначе пачка из тысячи задач напишет тысячу одинаковых строк.
_warned_prices: set[str] = set()
# Бюджеты, о превышении которых уже написали в лог — тоже раз на процесс.
_warned_budgets: set[str] = set()


@dataclass(frozen=True)
class Task:
    """Один вызов LLM: что спрашиваем, по какой схеме, чем платим."""

    user: str | None = None
    system: str | None = None
    messages: list[dict] | None = None
    schema: type[BaseModel] | dict | None = None  # None = обычный текст
    level: str | None = None
    chain: list[str] | None = None
    tags: dict[str, str] = field(default_factory=dict)
    default: Any = None
    temperature: float | None = None
    max_tokens: int | None = None
    timeout: float | None = None
    cache: bool | None = None
    retry: bool = True
    id: str | None = None


@dataclass
class Attempt:
    """Одна попытка одной модели."""

    model: str
    provider: str
    error_type: str | None = None
    error: str | None = None
    latency_ms: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0


@dataclass
class Answer:
    """Результат задачи и откуда он взялся."""

    data: Any
    source: str  # llm | cache | default
    model: str = ""
    provider: str = ""
    attempts: list[Attempt] = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    cost_known: bool = True
    latency_ms: int = 0
    warnings: list[str] = field(default_factory=list)
    error: str | None = None
    task_id: str | None = None

    @property
    def ok(self) -> bool:
        return self.source in ("llm", "cache")


@dataclass
class Stats:
    """Итоги за время жизни экземпляра `LlmKit`."""

    calls: int = 0
    cached: int = 0
    failed: int = 0
    fallbacks: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    seconds: float = 0.0
    by_model: Counter = field(default_factory=Counter)


@dataclass
class _Outcome:
    """Успешный сетевой вызов: данные плюс всё для учёта."""

    data: Any
    cache_value: Any
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    cost_known: bool = True


async def _sleep(seconds: float) -> None:
    """Пауза перед повтором; тесты подменяют эту функцию."""
    await asyncio.sleep(seconds)


def _litellm():
    """Ленивый импорт LiteLLM с заглушённым шумом (раздел 9)."""
    import litellm

    litellm.suppress_debug_info = True
    logging.getLogger("LiteLLM").setLevel(logging.WARNING)
    return litellm


def _instructor():
    """Ленивый импорт Instructor; его логгер тоже приглушаем."""
    import instructor

    logging.getLogger("instructor").setLevel(logging.WARNING)
    return instructor


def _default_instructor_factory(completion: Callable[..., Any], mode: str) -> Any:
    """Клиент Instructor поверх функции вызова модели."""
    instructor = _instructor()
    try:
        enum_mode = instructor.Mode[mode]
    except KeyError:
        raise ConfigError(f"неизвестный режим Instructor {mode!r}") from None
    return instructor.from_litellm(completion, mode=enum_mode)


def _strict_ok(schema: Any) -> bool:
    """Годится ли схема для strict-режима OpenAI: у каждого объекта
    `additionalProperties: false` и все свойства в `required`. Иначе провайдер
    отвергает запрос целиком — шлём без strict, ответ всё равно разбирается."""
    if isinstance(schema, list):
        return all(_strict_ok(item) for item in schema)
    if not isinstance(schema, dict):
        return True
    if schema.get("type") == "object" or "properties" in schema:
        props = schema.get("properties") or {}
        if schema.get("additionalProperties") is not False or set(schema.get("required") or []) != set(props):
            return False
    return all(_strict_ok(value) for key, value in schema.items() if key not in ("required", "enum", "const"))


def _mask(text: str, secret: str | None) -> str:
    """Убрать ключ провайдера из текста ошибки перед записью куда бы то ни было."""
    return text.replace(secret, "***") if secret else text


class _BudgetTracker:
    """Бюджеты задачи: журнал читается один раз, дальше считаем в памяти.

    Одно и то же предупреждение за задачу выдаётся один раз, даже если
    цепочка длинная и сетевых попыток было несколько.
    """

    def __init__(self, items: list[tuple[str, str, float, float]]) -> None:
        # (ключ бюджета, человеческое описание, лимит, потрачено сегодня)
        self._items = items
        self._reported: set[str] = set()

    def add(self, cost_usd: float) -> None:
        self._items = [(key, what, limit, spent + cost_usd) for key, what, limit, spent in self._items]

    def check(self) -> list[str]:
        """Новые предупреждения о превышении — по одному на бюджет за задачу."""
        fresh = []
        for key, what, limit, spent in self._items:
            if spent <= limit or key in self._reported:
                continue
            self._reported.add(key)
            text = f"{what} превышен: потрачено ${spent:.4f} за сегодня"
            if key not in _warned_budgets:
                _warned_budgets.add(key)
                log.warning("%s", text)
            fresh.append(text)
        return fresh


class LlmKit:
    """Точка входа: конфиг, кэш, журнал, цепочки моделей."""

    def __init__(
        self,
        *,
        config: Config | None = None,
        tags: dict[str, str] | None = None,
        completion: Callable[..., Any] | None = None,
        instructor_factory: Callable[[Callable[..., Any], str], Any] | None = None,
        level: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout: float | None = None,
        concurrency: int | None = None,
        cache: bool | None = None,
    ) -> None:
        overrides: dict[str, Any] = {}
        defaults = {
            "level": level,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "timeout": timeout,
            "concurrency": concurrency,
        }
        defaults = {key: value for key, value in defaults.items() if value is not None}
        if defaults:
            overrides["defaults"] = defaults
        if cache is not None:
            overrides["cache"] = {"enabled": cache}
        if config is None:
            self.config = config_mod.load(overrides=overrides)
        else:
            self.config = (
                config if not overrides else Config.model_validate(config_mod.merge(config.model_dump(), overrides))
            )
        if self.config.log_level:
            logging.getLogger("llmkit").setLevel(self.config.log_level)
        self.tags = dict(tags or {})
        self.cache = Cache(
            self.config.cache_path(),
            ttl_days=self.config.cache.ttl_days,
            enabled=self.config.cache.enabled,
        )
        self.usage = Usage(self.config.usage_path())
        self._completion = completion
        self._instructor_factory = instructor_factory or _default_instructor_factory
        self._instructor_clients: dict[tuple[str, Any], Any] = {}
        self._stats = Stats()

    # --- публичный API ---

    @property
    def stats(self) -> Stats:
        return self._stats

    async def ask(self, task: Task) -> Answer:
        """Пройти цепочку моделей и вернуть ответ.

        Сначала по кэшу проверяется вся цепочка: попадание отдаётся сразу,
        без сетевых вызовов и без ключей провайдеров. Потом идут сетевые
        попытки по порядку. Всё упало — `default` или `AllModelsFailed`.
        """
        started = time.perf_counter()
        messages = self._messages(task)
        chain = chain_mod.resolve(self.config, chain=task.chain, level=task.level)
        level = None if task.chain else (task.level or self.config.defaults.level)
        tags = {**self.tags, **task.tags}
        settings = self._settings(task)
        cache_enabled = task.cache if task.cache is not None else self.config.cache.enabled
        cache_keys = self._cache_keys(chain, messages, task, settings)

        attempts: list[Attempt] = []
        warnings: list[str] = []

        if cache_enabled:
            for position, ref in enumerate(chain):
                key = cache_keys.get(ref)
                cached = await self.cache.aget(key) if key else None
                if cached is None:
                    continue
                provider = ref.partition("/")[0]
                await self.usage.arecord(
                    model=ref, provider=provider, status="cache", task_id=task.id,
                    tags=tags, level=level, attempt=0,
                )
                answer = Answer(
                    data=self._decode(cached, task.schema), source="cache", model=ref,
                    provider=provider, attempts=attempts, warnings=warnings, task_id=task.id,
                )
                return self._done(answer, started, position, tags)

        budget = await self._budget_tracker(tags)
        for position, ref in enumerate(chain):
            try:
                call = providers_mod.build(ref, self.config)
            except KeyMissing as exc:
                await self._fail(task, tags, level, ref, ref.partition("/")[0], exc, "auth", attempts, 0)
                continue
            secret = call.params.get("api_key")

            retry_index = 0
            while True:
                warnings.extend(budget.check())
                begin = time.perf_counter()
                try:
                    outcome = await self._call_model(call, messages, task, settings)
                except Exception as exc:
                    error_type = chain_mod.classify(exc)
                    if error_type is None:
                        raise  # не ошибка провайдера, а наш баг — не маскируем
                    latency = int((time.perf_counter() - begin) * 1000)
                    await self._fail(
                        task, tags, level, call.ref, call.provider, exc, error_type,
                        attempts, retry_index, latency, secret,
                    )
                    allowed = chain_mod.retries_for(error_type, self.config.retry, exc) if task.retry else 0
                    if retry_index < allowed:
                        pause = chain_mod.backoff_seconds(error_type, retry_index, exc)
                        if pause:
                            await _sleep(pause)
                        retry_index += 1
                        continue
                    break

                latency = int((time.perf_counter() - begin) * 1000)
                budget.add(outcome.cost_usd)
                attempts.append(
                    Attempt(
                        model=call.ref, provider=call.provider, latency_ms=latency,
                        prompt_tokens=outcome.prompt_tokens, completion_tokens=outcome.completion_tokens,
                        cost_usd=outcome.cost_usd,
                    )
                )
                await self.usage.arecord(
                    model=call.ref, provider=call.provider, status="ok", task_id=task.id, tags=tags,
                    level=level, attempt=retry_index, prompt_tokens=outcome.prompt_tokens,
                    completion_tokens=outcome.completion_tokens, cost_usd=outcome.cost_usd,
                    cost_known=outcome.cost_known, latency_ms=latency,
                )
                key = cache_keys.get(call.ref)
                if cache_enabled and key:
                    await self.cache.aset(key, call.ref, outcome.cache_value)
                answer = Answer(
                    data=outcome.data, source="llm", model=call.ref, provider=call.provider,
                    attempts=attempts, prompt_tokens=outcome.prompt_tokens,
                    completion_tokens=outcome.completion_tokens, cost_usd=outcome.cost_usd,
                    cost_known=outcome.cost_known, warnings=warnings, task_id=task.id,
                )
                return self._done(answer, started, position, tags)

        answer = Answer(
            data=task.default, source="default", attempts=attempts, warnings=warnings,
            error=attempts[-1].error if attempts else "цепочка моделей пуста", task_id=task.id,
        )
        self._done(answer, started, max(len(chain) - 1, 0), tags)
        if task.default is None:
            raise AllModelsFailed(attempts, answer=answer)
        return answer

    async def generate(
        self, prompt: str, *, system: str | None = None, level: str | None = None, **task_kw: Any
    ) -> str | None:
        """Строковый путь: ошибок не бросает.

        Возвращает None, если ответа нет; если у задачи задан `default`,
        возвращается он (приведённый к строке).
        """
        task = Task(user=prompt, system=system, level=level, **task_kw)
        try:
            answer = await self.ask(task)
        except LlmKitError as exc:
            log.warning("generate: ответа нет (%s)", exc)
            return None
        if not answer.ok:
            log.warning("generate: ответа нет (%s)", answer.error)
        if answer.data is None:
            return None
        return answer.data if isinstance(answer.data, str) else str(answer.data)

    async def ask_many(
        self,
        tasks: Sequence[Task],
        *,
        concurrency: int | None = None,
        on_progress: Callable[[int, int, Answer], None] | None = None,
        raise_on_error: bool = False,
    ) -> list[Answer]:
        """Пачка задач: порядок результатов совпадает с порядком задач.

        Упавшая задача не рвёт пачку — она отдаётся как `source="default"`.
        С `raise_on_error=True` первая ошибка отменяет оставшиеся задачи.
        """
        total = len(tasks)
        limit = concurrency or self.config.defaults.concurrency
        semaphore = asyncio.Semaphore(max(limit, 1))
        done = 0

        async def one(task: Task) -> Answer:
            nonlocal done
            async with semaphore:
                try:
                    answer = await self.ask(task)
                except AllModelsFailed as exc:
                    if raise_on_error:
                        raise
                    answer = exc.answer or Answer(
                        data=task.default, source="default", attempts=exc.attempts,
                        error=str(exc), task_id=task.id,
                    )
            done += 1
            self._notify(on_progress, done, total, answer)
            return answer

        if not raise_on_error:
            return list(await asyncio.gather(*(one(task) for task in tasks)))
        try:
            async with asyncio.TaskGroup() as group:
                running = [group.create_task(one(task)) for task in tasks]
        except* AllModelsFailed as errors:
            # TaskGroup уже отменил остальные задачи — наружу отдаём первую ошибку.
            raise errors.exceptions[0] from None
        return [item.result() for item in running]

    @staticmethod
    def _notify(
        on_progress: Callable[[int, int, Answer], None] | None, done: int, total: int, answer: Answer
    ) -> None:
        """Колбэк прогресса не должен рвать пачку своей ошибкой."""
        if on_progress is None:
            return
        try:
            on_progress(done, total, answer)
        except Exception:
            log.exception("on_progress упал на задаче %s", answer.task_id)

    # --- sync-обёртки ---

    def ask_sync(self, task: Task) -> Answer:
        from ._sync import run

        return run(self.ask(task))

    def generate_sync(self, prompt: str, **kwargs: Any) -> str | None:
        from ._sync import run

        return run(self.generate(prompt, **kwargs))

    def ask_many_sync(self, tasks: Sequence[Task], **kwargs: Any) -> list[Answer]:
        from ._sync import run

        return run(self.ask_many(tasks, **kwargs))

    async def aclose(self) -> None:
        """Ресурсов, живущих между вызовами, нет; метод есть для симметрии API."""

    def close(self) -> None:
        """Ресурсов, живущих между вызовами, нет; метод есть для симметрии API."""

    # --- внутреннее ---

    def _settings(self, task: Task) -> dict[str, Any]:
        defaults = self.config.defaults
        return {
            "temperature": defaults.temperature if task.temperature is None else task.temperature,
            "max_tokens": defaults.max_tokens if task.max_tokens is None else task.max_tokens,
            "timeout": defaults.timeout if task.timeout is None else task.timeout,
        }

    def _messages(self, task: Task) -> list[dict]:
        if task.messages:
            return [dict(message) for message in task.messages]
        if not task.user:
            raise LlmKitError("задаче нужен user или messages")
        messages = []
        if task.system:
            messages.append({"role": "system", "content": task.system})
        messages.append({"role": "user", "content": task.user})
        return messages

    def _done(self, answer: Answer, started: float, position: int, tags: dict[str, str]) -> Answer:
        """Досчитать статистику, записать строку INFO и отдать ответ."""
        self._finish(answer, started, position)
        log.info(
            "%s %s tokens=%d/%d cost=$%.6f %dms tags=%s",
            answer.model or "—", answer.source, answer.prompt_tokens, answer.completion_tokens,
            answer.cost_usd, answer.latency_ms, tags,
        )
        return answer

    def _cache_keys(
        self, chain: list[str], messages: list[dict], task: Task, settings: dict
    ) -> dict[str, str]:
        """Ключ кэша для каждой модели цепочки — до резолва ключей провайдеров."""
        keys: dict[str, str] = {}
        for ref in chain:
            try:
                base = providers_mod.api_base(ref, self.config)
            except ConfigError:
                continue  # ошибка конфига всплывёт на сетевом шаге
            keys[ref] = cache_mod.make_key(
                model=ref,
                api_base=base,
                messages=messages,
                schema=task.schema,
                temperature=settings["temperature"],
                max_tokens=settings["max_tokens"],
            )
        return keys

    def _finish(self, answer: Answer, started: float, position: int) -> None:
        answer.latency_ms = int((time.perf_counter() - started) * 1000)
        self._stats.seconds += time.perf_counter() - started
        self._stats.calls += 1
        if answer.source == "cache":
            self._stats.cached += 1
        elif answer.source == "default":
            self._stats.failed += 1
        self._stats.fallbacks += max(position, 0)
        self._stats.prompt_tokens += answer.prompt_tokens
        self._stats.completion_tokens += answer.completion_tokens
        self._stats.cost_usd += answer.cost_usd
        if answer.model:
            self._stats.by_model[answer.model] += 1

    async def _fail(
        self,
        task: Task,
        tags: dict[str, str],
        level: str | None,
        ref: str,
        provider: str,
        exc: BaseException,
        error_type: str,
        attempts: list[Attempt],
        retry_index: int,
        latency_ms: int = 0,
        secret: str | None = None,
    ) -> str:
        """Записать провалившуюся попытку в `attempts`, usage и лог."""
        message = _mask(f"{type(exc).__name__}: {exc}", secret)[:500]
        attempts.append(
            Attempt(model=ref, provider=provider, error_type=error_type, error=message, latency_ms=latency_ms)
        )
        await self.usage.arecord(
            model=ref, provider=provider, status="failed", task_id=task.id, tags=tags, level=level,
            attempt=retry_index, error_type=error_type, latency_ms=latency_ms,
        )
        logger = log.error if error_type == "auth" else log.debug
        logger("%s: %s (%s)", ref, error_type, message)
        return error_type

    async def _budget_tracker(self, tags: dict[str, str]) -> _BudgetTracker:
        """Прочитать потраченное за сегодня — один раз на задачу."""
        budget = self.config.budget
        items: list[tuple[str, str, float, float]] = []
        if budget.daily_usd is not None:
            items.append(
                ("daily", f"дневной бюджет ${budget.daily_usd}", budget.daily_usd, await self.usage.aspent_today())
            )
        for tag, limit in budget.tags.items():
            name, _, value = tag.partition("=")
            if tags.get(name) == value:
                items.append((tag, f"бюджет метки {tag} ${limit}", limit, await self.usage.aspent_today(tag=tag)))
        return _BudgetTracker(items)

    @staticmethod
    def _decode(cached: Any, schema: Any) -> Any:
        """Развернуть значение из кэша обратно в тип, который ждёт задача."""
        validate = getattr(schema, "model_validate", None)
        if callable(validate) and isinstance(cached, dict):
            return validate(cached)
        return cached

    async def _call_model(self, call: providers_mod.ModelCall, messages: list[dict], task: Task, settings: dict) -> _Outcome:
        # Подмена из тестов → свой транспорт провайдера по подписке → LiteLLM.
        completion = self._completion or call.completion
        if completion is None:
            completion = _litellm().acompletion
        kwargs = {
            "model": call.litellm_model,
            "messages": messages,
            "temperature": settings["temperature"],
            "max_tokens": settings["max_tokens"],
            "timeout": settings["timeout"],
            **call.params,
        }
        if call.completion is None:
            # Параметр, который модель не принимает (temperature=0 у рассуждающих
            # GPT-5/6), LiteLLM молча отбрасывает, а не отклоняет весь запрос.
            kwargs["drop_params"] = True
        if task.schema is None:
            response = await completion(**kwargs)
            text = self._text_of(response)
            return self._outcome(call, response, data=text, cache_value=text)
        if isinstance(task.schema, dict):
            response = await completion(
                response_format={
                    "type": "json_schema",
                    "json_schema": {"name": "answer", "schema": task.schema, "strict": _strict_ok(task.schema)},
                },
                **kwargs,
            )
            text = self._text_of(response)
            try:
                data = json.loads(text)
            except ValueError as exc:
                raise chain_mod.JsonParseFailed(f"ответ не разобрался как JSON: {exc}") from exc
            return self._outcome(call, response, data=data, cache_value=data)
        return await self._call_structured(call, messages, task, kwargs, completion)

    async def _call_structured(
        self,
        call: providers_mod.ModelCall,
        messages: list[dict],
        task: Task,
        kwargs: dict,
        completion: Callable[..., Any],
    ) -> _Outcome:
        """JSON по pydantic-схеме через Instructor: ретраи внутри вызова."""
        key = (call.mode, completion)
        client = self._instructor_clients.get(key)
        if client is None:
            client = self._instructor_factory(completion, call.mode)
            self._instructor_clients[key] = client
        data, response = await client.chat.completions.create_with_completion(
            response_model=task.schema,
            max_retries=self.config.retry.invalid_output if task.retry else 0,
            **kwargs,
        )
        dump = getattr(data, "model_dump", None)
        cache_value = dump(mode="json") if callable(dump) else data
        return self._outcome(call, response, data=data, cache_value=cache_value)

    @staticmethod
    def _text_of(response: Any) -> str:
        choices = getattr(response, "choices", None) or []
        if not choices:
            raise chain_mod.EmptyResponse("провайдер вернул ответ без choices")
        choice = choices[0]
        if getattr(choice, "finish_reason", None) == "content_filter":
            raise chain_mod.ContentFiltered("ответ отклонён контент-фильтром провайдера")
        text = getattr(getattr(choice, "message", None), "content", None) or ""
        if not text.strip():
            raise chain_mod.EmptyResponse("модель вернула пустой ответ")
        return text

    def _outcome(self, call: providers_mod.ModelCall, response: Any, *, data: Any, cache_value: Any) -> _Outcome:
        usage = getattr(response, "usage", None)
        prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
        completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
        cost, known = self._cost(call, response, prompt_tokens, completion_tokens)
        return _Outcome(
            data=data, cache_value=cache_value, prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens, cost_usd=cost, cost_known=known,
        )

    def _cost(self, call: providers_mod.ModelCall, response: Any, prompt_tokens: int, completion_tokens: int) -> tuple[float, bool]:
        """Стоимость: подписка → цены из конфига → LiteLLM → неизвестно (один варн на модель).

        Конфиг главнее справочника LiteLLM: у шлюзов (ccode) имя модели совпадает
        с вендорским, и LiteLLM отдал бы прайс вендора, а не шлюза.
        """
        if call.subscription:
            return 0.0, True  # оплачено подпиской, отдельного счёта за вызов нет
        from_config = providers_mod.price_from_config(self.config, call, prompt_tokens, completion_tokens)
        if from_config is not None:
            return from_config, True
        cost = 0.0
        # litellm импортируем только если он и так в игре: с подменённым
        # `completion` (тесты) модуль тянуть незачем.
        litellm = sys.modules.get("litellm") or (_litellm() if self._completion is None else None)
        if litellm is not None:
            try:
                cost = float(litellm.completion_cost(completion_response=response) or 0.0)
            except Exception as exc:  # цену знает не каждая модель
                log.debug("completion_cost для %s не сработал: %s", call.ref, exc)
        if cost > 0:
            return cost, True
        if prompt_tokens == 0 and completion_tokens == 0:
            return 0.0, True
        if call.ref not in _warned_prices:
            _warned_prices.add(call.ref)
            log.warning("цена модели %s неизвестна: расход не учитывается", call.ref)
        return 0.0, False
