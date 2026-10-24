"""Данные задачи и ответа: Task, Attempt, Answer, Stats (раздел 5)."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel


@dataclass(frozen=True)
class Task:
    """Один вызов LLM: что спрашиваем, по какой схеме, чем платим."""

    user: str | None = None
    system: str | None = None
    messages: list[dict] | None = None
    schema: type[BaseModel] | dict | None = None  # None = обычный текст
    chain: list[str] | None = None  # вместо routing.chain; провайдеры — из routing
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
    cost_usd: float | None = 0.0  # None — цена неизвестна
    cost_source: str | None = None  # как у Answer
    billable: bool = False  # провайдер списал вызов: ответ получен (в т.ч. неразобранный) или подписка


@dataclass
class Answer:
    """Результат задачи и откуда он взялся."""

    data: Any
    source: str  # llm | cache | default
    model: str = ""  # элемент цепочки, который ответил: "провайдер/модель"
    provider: str = ""
    attempts: list[Attempt] = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float | None = 0.0  # стоимость ответившей попытки; None — цена неизвестна
    # provider (списано, из ответа) | price_table (цена × токены: routing.prices, затем LiteLLM)
    # | subscription | cache | None (неизвестно)
    cost_source: str | None = "price_table"
    latency_ms: int = 0
    warnings: list[str] = field(default_factory=list)
    error: str | None = None
    task_id: str | None = None
    # Версия, которую назвал провайдер (за алиасом вида `~…-latest`); не назвал — `model`.
    served_model: str = ""
    chain_position: int = 0  # 0-based номер ответившей модели в цепочке
    billable_requests: int = 0  # платные вызовы провайдера за задачу: все попытки с `billable`
    cost_total: float | None = 0.0  # сумма по платным попыткам; None — цена хоть одной неизвестна

    @property
    def ok(self) -> bool:
        return self.source in ("llm", "cache")

    @property
    def cache_hit(self) -> bool:
        return self.source == "cache"

    @property
    def cost_known(self) -> bool:
        return self.cost_source is not None


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
class Outcome:
    """Успешный сетевой вызов: данные плюс всё для учёта."""

    data: Any
    cache_value: Any
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float | None = 0.0
    cost_source: str | None = "price_table"
    served_model: str = ""

    @property
    def billable(self) -> bool:
        """Провайдер списал ответ. Ответ без токенов ответа не списывается (zero completion insurance OpenRouter)."""
        if self.cost_source == "provider":
            return bool(self.cost_usd)
        return self.cost_source == "subscription" or self.completion_tokens > 0


def totals(attempts: list[Attempt]) -> tuple[int, float | None]:
    """billable_requests и cost_total по попыткам задачи."""
    billable = [attempt for attempt in attempts if attempt.billable]
    if any(attempt.cost_usd is None for attempt in billable):
        return len(billable), None
    return len(billable), sum(attempt.cost_usd or 0.0 for attempt in billable)
