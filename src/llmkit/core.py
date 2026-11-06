"""LlmKit: ask / generate / ask_many через шлюз 9router — один вызов, один запрос (ADR-0001)."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from . import cache as cache_mod
from . import config as config_mod
from . import keys as keys_mod
from . import routing as routing_mod
from .cache import Cache
from .callutil import mask, messages_of, parse_json
from .config import Config
from .errors import AllModelsFailed, GatewayUnavailable, LlmKitError, RoutingInvalid, RoutingMissing
from .models import Answer, Attempt, Outcome, Stats, Task, totals
from .routing import Routing
from .usage import Usage

if TYPE_CHECKING:  # pragma: no cover
    from .gateway import GatewayClient
    from .gateway.parse import Reply

log = logging.getLogger("llmkit.core")

# Бюджеты, о превышении которых уже написали в лог — раз на процесс.
_warned_budgets: set[str] = set()

# Цен в llmkit больше нет (ADR-0001), но набор остаётся: фикстура tests/conftest.py чистит его перед каждым тестом.
_warned_prices: set[str] = set()

# Повтор невалидного ответа несёт текст ошибки проверки: иначе модель повторит тот же ответ.
RETRY_PROMPT = "Ответ не прошёл проверку схемы: {error}. Верни JSON по схеме."


class _BudgetTracker:
    """Бюджеты задачи: журнал читается один раз, дальше считаем в памяти."""

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
    """Точка входа: routing (адрес шлюза и модели), настройки, кэш, журнал."""

    def __init__(
        self,
        *,
        routing: Routing | dict[str, Any] | None = None,
        config: Config | None = None,
        tags: dict[str, str] | None = None,
        transport: Any = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout: float | None = None,
        concurrency: int | None = None,
        cache: bool | None = None,
    ) -> None:
        # Без routing экземпляр создаётся, а первый вызов бросит RoutingMissing.
        self.routing = None if routing is None else routing_mod.parse(routing, require_chain=False)
        overrides: dict[str, Any] = {}
        defaults = {
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
        self.usage = Usage(self.config.usage_path())
        self.cache = Cache(
            self.usage._db,
            ttl_days=self.config.cache.ttl_days,
            enabled=self.config.cache.enabled,
        )
        # Подмена сети в тестах: httpx.MockTransport вместо настоящего шлюза.
        self._transport = transport
        self._stats = Stats()
        # Подготовка вызова (кэш, бюджеты) идёт в порядке задач пачки: запросы уходят тем же порядком.
        self._prep = asyncio.Lock()

    # --- публичный API ---

    @property
    def stats(self) -> Stats:
        return self._stats

    async def ask(self, task: Task) -> Answer:
        """Спросить шлюз и вернуть ответ: текст, значение схемы или `default`.

        Кэш — по запрошенной модели и сообщениям. Сбой шлюза (`GatewayUnavailable`)
        и невалидный ответ (`AllModelsFailed`) бросаются, если `default` не задан;
        повторов на другой модели и фолбэка у llmkit нет — это дело шлюза.
        """
        started = time.perf_counter()
        provider, cfg, model = self._route()
        messages = messages_of(task)
        settings = self._settings(task)
        tags = {**self.tags, **task.tags}
        warnings: list[str] = []
        key = cache_mod.make_key(
            model=model,
            api_base=cfg.base_url,
            messages=messages,
            schema=task.schema,
            temperature=settings["temperature"],
            max_tokens=settings["max_tokens"],
        )
        cache_enabled = self.config.cache.enabled if task.cache is None else task.cache
        async with self._prep:
            cached = await self.cache.aget_safe(key, warnings) if cache_enabled else None
            if cached is not None:
                data, reply = self._replay(cached)
                await self._record(
                    task,
                    tags,
                    Attempt(
                        model=model, provider=reply.get("provider") or provider, cost_source="cache", billable=False
                    ),
                    status="cache",
                )
                answer = Answer(
                    data=self._decode(data, task.schema),
                    source="cache",
                    model=model,
                    provider=reply.get("provider") or provider,
                    cost_usd=reply.get("cost_usd"),
                    cost_source="cache",
                    prompt_tokens=reply.get("prompt_tokens", 0),
                    completion_tokens=reply.get("completion_tokens", 0),
                    billable_requests=0,
                    cost_total=0.0,
                    warnings=warnings,
                    task_id=task.id,
                    served_model=reply.get("served_model") or model,
                )
                return self._done(answer, started, tags)
            # Бюджеты читаются там же: задачи пачки не должны обгонять друг друга до самого запроса.
            budget = await self._budget_tracker(tags)

        from .gateway import GatewayClient  # httpx тянет rich и click: импорт отложен ради быстрого старта

        secret = keys_mod.resolve(provider, cfg, warnings=warnings)
        client = GatewayClient(
            cfg.base_url or "", api_key=secret, transport=self._transport, timeout=settings["timeout"]
        )
        begun = time.perf_counter()
        try:
            outcome, spent = await self._call(client, task, messages, model, settings)
        except AllModelsFailed as exc:
            for attempt in exc.attempts:
                await self._record(task, tags, attempt, status="failed")
            raise
        except GatewayUnavailable as exc:
            attempt = Attempt(
                model=model,
                provider=provider,
                error_type=exc.kind,
                error=mask(str(exc), secret),
                latency_ms=int((time.perf_counter() - begun) * 1000),
            )
            await self._record(task, tags, attempt, status="failed")
            raise
        latency = int((time.perf_counter() - begun) * 1000)
        budget.add(outcome.cost_usd or 0.0)
        warnings.extend(budget.check())
        if outcome.cost_usd is None:
            # Цены в ответе шлюза нет — одно предупреждение на модель и вызов.
            message = f"price unknown for {model}"
            if message not in warnings:
                warnings.append(message)
        attempt = Attempt(
            model=model,
            provider=outcome.provider,
            latency_ms=latency,
            prompt_tokens=outcome.prompt_tokens,
            completion_tokens=outcome.completion_tokens,
            cost_usd=outcome.cost_usd,
            cost_source=outcome.cost_source,
            billable=True,
        )
        served = outcome.served_model or model
        for failed in spent:
            await self._record(task, tags, failed, status="failed")
        await self._record(task, tags, attempt, status="ok", served_model=served)
        if cache_enabled:
            await self.cache.aset_safe(key, model, self._cache_value(outcome), warnings)
        billable_requests, cost_total = totals([*spent, attempt])
        answer = Answer(
            data=outcome.data,
            source="llm",
            model=model,
            provider=outcome.provider,
            attempts=[*spent, attempt],
            prompt_tokens=outcome.prompt_tokens,
            completion_tokens=outcome.completion_tokens,
            cost_usd=outcome.cost_usd,
            cost_source=outcome.cost_source,
            warnings=warnings,
            task_id=task.id,
            served_model=served,
            billable_requests=billable_requests,
            cost_total=cost_total,
        )
        return self._done(answer, started, tags)

    async def generate(self, prompt: str, *, system: str | None = None, **task_kw: Any) -> str | None:
        """Строковый путь: ошибок не бросает.

        Возвращает None, если ответа нет; если у задачи задан `default`,
        возвращается он (приведённый к строке).
        """
        task = Task(user=prompt, system=system, **task_kw)
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
                except LlmKitError as exc:
                    if raise_on_error:
                        raise
                    attempts = getattr(exc, "attempts", None) or []
                    answer = Answer(
                        data=task.default,
                        source="default",
                        attempts=attempts,
                        error=str(exc),
                        task_id=task.id,
                    )
            done += 1
            self._notify(on_progress, done, total, answer)
            return answer

        if not raise_on_error:
            return list(await asyncio.gather(*(one(task) for task in tasks)))
        try:
            async with asyncio.TaskGroup() as group:
                running = [group.create_task(one(task)) for task in tasks]
        except BaseExceptionGroup as group:
            # TaskGroup уже отменил остальные задачи — наружу отдаём первую ошибку. Не `except*`: на Python 3.11.2
            # исключение, брошенное из его тела, снова оборачивается в ExceptionGroup.
            failed = group.subgroup(LlmKitError)
            if failed is None:
                raise
            raise failed.exceptions[0] from None
        return [item.result() for item in running]

    @staticmethod
    def _notify(on_progress: Callable[[int, int, Answer], None] | None, done: int, total: int, answer: Answer) -> None:
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
        """Закрыть соединения журнала с базой (`Usage.close`)."""
        self.usage.close()

    def close(self) -> None:
        """Закрыть соединения журнала с базой (`Usage.close`)."""
        self.usage.close()

    # --- внутреннее ---

    def _route(self) -> tuple[str, routing_mod.Provider, str]:
        """Провайдер шлюза и модель вызова: первый провайдер routing и первая модель цепочки."""
        if self.routing is None:
            raise RoutingMissing()
        chain = self.routing.chain or []
        if not chain:
            raise RoutingInvalid("/chain", "нет цепочки моделей: передайте chain в routing или -m в CLI")
        name, cfg = next(iter(self.routing.providers.items()))
        return name, cfg, chain[0]

    def _settings(self, task: Task) -> dict[str, Any]:
        defaults = self.config.defaults
        return {
            "temperature": defaults.temperature if task.temperature is None else task.temperature,
            "max_tokens": defaults.max_tokens if task.max_tokens is None else task.max_tokens,
            "timeout": defaults.timeout if task.timeout is None else task.timeout,
        }

    async def _call(
        self, client: GatewayClient, task: Task, messages: list[dict], model: str, settings: dict[str, Any]
    ) -> tuple[Outcome, list[Attempt]]:
        """Запрос к шлюзу; невалидный ответ повторяется с текстом ошибки, не больше retry.invalid_output.

        Возвращает результат и уже оплаченные неудачные попытки — их тоже пишем в журнал.
        """
        retries = self.config.retry.invalid_output if task.retry else 0
        sent = messages
        spent: list[Attempt] = []
        for left in range(retries, -1, -1):
            begun = time.perf_counter()
            reply = await client.chat(self._body(model, sent, task, settings))
            latency = int((time.perf_counter() - begun) * 1000)
            data, error_type, error = self._read(reply, task.schema)
            if error is None:
                return self._outcome(reply, data), spent
            attempt = self._attempt(model, reply, error_type, error)
            attempt.latency_ms = latency
            spent.append(attempt)
            if left == 0:
                billable_requests, cost_total = totals(spent)
                answer = Answer(
                    data=None,
                    source="default",
                    model=model,
                    attempts=spent,
                    billable_requests=billable_requests,
                    cost_total=cost_total,
                )
                raise AllModelsFailed(spent, answer=answer)
            sent = [
                *messages,
                {"role": "assistant", "content": reply.text},
                {"role": "user", "content": RETRY_PROMPT.format(error=error)},
            ]
        raise AssertionError("цикл повторов не выполнился")  # pragma: no cover

    def _body(self, model: str, messages: list[dict], task: Task, settings: dict[str, Any]) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            # Шлюз пишет в журнал только поточные вызовы — stream всегда true.
            "stream": True,
            "temperature": settings["temperature"],
            "max_tokens": settings["max_tokens"],
        }
        schema = self._json_schema(task.schema)
        if schema is not None:
            body["response_format"] = {"type": "json_schema", "json_schema": {"name": "answer", "schema": schema}}
        return body

    @staticmethod
    def _json_schema(schema: Any) -> dict | None:
        if schema is None:
            return None
        if isinstance(schema, dict):
            return schema
        return schema.model_json_schema()

    @staticmethod
    def _read(reply: Reply, schema: Any) -> tuple[Any, str | None, str | None]:
        """(данные, вид ошибки, текст ошибки) — ответ шлюза для задачи."""
        if reply.finish_reason == "content_filter":
            return None, "refusal", "шлюз отклонил ответ контент-фильтром"
        if not reply.text.strip():
            return None, "invalid_output", "шлюз вернул пустой ответ"
        try:
            return LlmKit._decode_text(reply.text, schema), None, None
        except (ValueError, ValidationError) as exc:
            return None, "invalid_output", str(exc)

    @staticmethod
    def _decode_text(text: str, schema: Any) -> Any:
        if schema is None:
            return text
        if isinstance(schema, dict):
            return parse_json(text)
        return schema.model_validate_json(text)

    def _attempt(self, model: str, reply: Reply, error_type: str | None, error: str | None) -> Attempt:
        return Attempt(
            model=model,
            provider=reply.provider,
            error_type=error_type,
            error=error,
            prompt_tokens=reply.prompt_tokens,
            completion_tokens=reply.completion_tokens,
            cost_usd=reply.cost_usd,
            cost_source="provider" if reply.cost_usd is not None else None,
            billable=bool(reply.completion_tokens or reply.cost_usd),
        )

    @staticmethod
    def _cache_value(outcome: Outcome) -> dict[str, Any]:
        """Запись кэша: данные плюс поля ответа шлюза — попадание в кэш отвечает так же, как шлюз."""
        return {
            "data": outcome.cache_value,
            "reply": {
                "served_model": outcome.served_model,
                "provider": outcome.provider,
                "cost_usd": outcome.cost_usd,
                "prompt_tokens": outcome.prompt_tokens,
                "completion_tokens": outcome.completion_tokens,
            },
        }

    @staticmethod
    def _replay(cached: Any) -> tuple[Any, dict[str, Any]]:
        """Запись кэша → (данные, поля ответа шлюза); запись старого вида — только данные."""
        if isinstance(cached, dict) and set(cached) == {"data", "reply"}:
            return cached["data"], cached["reply"]
        return cached, {}

    def _outcome(self, reply: Reply, data: Any) -> Outcome:
        dump = getattr(data, "model_dump", None)
        cache_value = dump(mode="json") if callable(dump) else data
        return Outcome(
            data=data,
            cache_value=cache_value,
            prompt_tokens=reply.prompt_tokens,
            completion_tokens=reply.completion_tokens,
            cost_usd=reply.cost_usd,
            cost_source="provider" if reply.cost_usd is not None else None,
            served_model=reply.served_model,
            provider=reply.provider,
        )

    def _done(self, answer: Answer, started: float, tags: dict[str, str]) -> Answer:
        """Досчитать статистику, записать строку INFO и отдать ответ."""
        answer.latency_ms = int((time.perf_counter() - started) * 1000)
        self._stats.seconds += time.perf_counter() - started
        self._stats.calls += 1
        if answer.source == "cache":
            self._stats.cached += 1
        elif answer.source == "default":
            self._stats.failed += 1
        self._stats.prompt_tokens += answer.prompt_tokens
        self._stats.completion_tokens += answer.completion_tokens
        self._stats.cost_usd += answer.cost_total or 0.0
        if answer.model:
            self._stats.by_model[answer.model] += 1
        log.info(
            "%s %s tokens=%d/%d cost=$%.6f %dms tags=%s",
            answer.model or "—",
            answer.source,
            answer.prompt_tokens,
            answer.completion_tokens,
            answer.cost_usd or 0.0,
            answer.latency_ms,
            tags,
        )
        return answer

    async def _record(
        self,
        task: Task,
        tags: dict[str, str],
        attempt: Attempt,
        *,
        status: str,
        served_model: str | None = None,
    ) -> None:
        await self.usage.arecord(
            model=attempt.model,
            provider=attempt.provider or "",
            status=status,
            task_id=task.id,
            tags=tags,
            attempt=0,
            error_type=attempt.error_type,
            prompt_tokens=attempt.prompt_tokens,
            completion_tokens=attempt.completion_tokens,
            cost_usd=attempt.cost_usd or 0.0,
            cost_known=attempt.cost_source is not None,
            cost_source=attempt.cost_source,
            billable=attempt.billable,
            latency_ms=attempt.latency_ms,
            served_model=served_model or attempt.model,
        )

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
