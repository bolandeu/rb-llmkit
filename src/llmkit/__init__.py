"""llmkit — общий LLM-слой: цепочки моделей, кэш, учёт расходов.

Быстрый импорт: litellm и instructor подтягиваются лениво, уже в пути вызова.
"""

from __future__ import annotations

from .config import Config
from .core import Answer, Attempt, LlmKit, Stats, Task
from .errors import (
    AllModelsFailed,
    ConfigError,
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
