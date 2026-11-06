"""LlmKit: ask / generate / ask_many через шлюз 9router — один вызов, один запрос (ADR-0001)."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from . import config as config_mod
from . import keys as keys_mod
from . import routing as routing_mod
from .callutil import messages_of, parse_json
from .config import Config
from .errors import AllModelsFailed, GatewayUnavailable, LlmKitError, RoutingInvalid, RoutingMissing
from .models import Answer, Attempt, Outcome, Stats, Task, totals
from .routing import Routing

if TYPE_CHECKING:  # pragma: no cover
    from .gateway import GatewayClient
    from .gateway.parse import Reply

log = logging.getLogger("llmkit.core")

# Повтор невалидного ответа несёт текст ошибки проверки: иначе модель повторит тот же ответ.
RETRY_PROMPT = "Ответ не прошёл проверку схемы: {error}. Верни JSON по схеме."


class LlmKit:
    """Точка входа: routing (адрес шлюза и модели), настройки вызова, подмена сети в тестах."""

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
        if config is None:
            self.config = config_mod.load(overrides=overrides)
        else:
            self.config = (
                config if not overrides else Config.model_validate(config_mod.merge(config.model_dump(), overrides))
            )
        if self.config.log_level:
            logging.getLogger("llmkit").setLevel(self.config.log_level)
        self.tags = dict(tags or {})
        # Подмена сети в тестах: httpx.MockTransport вместо настоящего шлюза.
        self._transport = transport
        self._stats = Stats()

    # --- публичный API ---

    @property
    def stats(self) -> Stats:
        return self._stats

    async def ask(self, task: Task) -> Answer:
        """Спросить шлюз и вернуть ответ: текст, значение схемы или `default`.

        Сбой шлюза (`GatewayUnavailable`) и невалидный ответ (`AllModelsFailed`)
        бросаются, если `default` не задан; повторов на другой модели и фолбэка
        у llmkit нет — это дело шлюза.
        """
        started = time.perf_counter()
        provider, cfg, model = self._route()
        messages = messages_of(task)
        settings = self._settings(task)
        tags = {**self.tags, **task.tags}

        from .gateway import GatewayClient  # httpx тянет rich и click: импорт отложен ради быстрого старта

        warnings: list[str] = []
        secret = keys_mod.resolve(provider, cfg)
        client = GatewayClient(
            cfg.base_url or "", api_key=secret, transport=self._transport, timeout=settings["timeout"]
        )
        begun = time.perf_counter()
        try:
            outcome, spent = await self._call(client, task, messages, model, settings)
        except GatewayUnavailable:
            raise
        latency = int((time.perf_counter() - begun) * 1000)
        if outcome.cost_usd is None:
            # Цены в ответе шлюза нет — одно предупреждение на вызов.
            warnings.append(f"price unknown for {model}")
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
            served_model=outcome.served_model or model,
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

        Возвращает результат и уже оплаченные неудачные попытки.
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

    def _outcome(self, reply: Reply, data: Any) -> Outcome:
        return Outcome(
            data=data,
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
        if answer.source == "default":
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
