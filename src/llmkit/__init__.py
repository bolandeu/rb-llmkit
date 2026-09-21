"""llmkit — общий LLM-слой: цепочки моделей, кэш, учёт расходов.

Быстрый импорт: litellm и instructor подтягиваются лениво, уже в пути вызова.
"""

from __future__ import annotations

from .config import Config
from .config import load as load_config
from .core import Answer, Attempt, LlmKit, Stats, Task
from .errors import AllModelsFailed, ConfigError, KeyMissing, LlmKitError

__all__ = [
    "AllModelsFailed",
    "Answer",
    "Attempt",
    "Config",
    "ConfigError",
    "KeyMissing",
    "LlmKit",
    "LlmKitError",
    "Stats",
    "Task",
    "load_config",
]
