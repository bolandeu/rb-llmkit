"""llmkit — общий LLM-слой: вызовы моделей через шлюз 9router, типизированный ответ, учёт расходов.

Быстрый импорт: HTTP-клиент шлюза (httpx) и тяжёлые части журнала подтягиваются лениво.
"""

from __future__ import annotations

from .config import Config
from .core import Answer, Attempt, LlmKit, Stats, Task
from .errors import (
    AllModelsFailed,
    ConfigError,
    GatewayUnavailable,
    KeyMissing,
    LlmKitError,
    RoutingInvalid,
    RoutingMissing,
    TemplateError,
    TemplateVariableMissing,
)
from .routing import Routing
from .routing import parse as parse_routing
from .template import render

__all__ = [
    "AllModelsFailed",
    "Answer",
    "Attempt",
    "Config",
    "ConfigError",
    "GatewayUnavailable",
    "KeyMissing",
    "LlmKit",
    "LlmKitError",
    "Routing",
    "RoutingInvalid",
    "RoutingMissing",
    "Stats",
    "Task",
    "TemplateError",
    "TemplateVariableMissing",
    "parse_routing",
    "render",
]
