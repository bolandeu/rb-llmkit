"""llmkit — общий LLM-слой: вызовы моделей через шлюз 9router, типизированный ответ, учёт расходов.

Быстрый импорт: `pydantic` и httpx приходят с первым обращением к `LlmKit`, `Answer`,
`Routing` и прочим моделям, а не с `import llmkit` (AGENTS.md: меньше 300 мс даже без
.pyc-кэша). Имена в `__all__` доступны как раньше — через `__getattr__` (PEP 562).
"""

from __future__ import annotations

import importlib
from typing import Any

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

# имя в пакете → (модуль, имя в модуле): грузится при первом обращении
_LAZY: dict[str, tuple[str, str]] = {
    "Answer": ("core", "Answer"),
    "Attempt": ("core", "Attempt"),
    "LlmKit": ("core", "LlmKit"),
    "Stats": ("core", "Stats"),
    "Task": ("core", "Task"),
    "Config": ("config", "Config"),
    "Routing": ("routing", "Routing"),
    "parse_routing": ("routing", "parse"),
    "render": ("template", "render"),
}

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


def __getattr__(name: str) -> Any:
    """Ленивая выдача имён из `_LAZY`: модуль грузится при первом обращении."""
    target = _LAZY.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module, attribute = target
    value = getattr(importlib.import_module(f".{module}", __name__), attribute)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(__all__)
