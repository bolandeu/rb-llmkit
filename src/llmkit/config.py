"""Настройки вызовов: дефолты в коде → env `LLMKIT_*` → аргументы `LlmKit(...)`.

Файлов конфига нет: провайдеры и цепочка приходят данными (routing v1,
`routing.py`). Своего состояния у llmkit нет: ни базы, ни кэша — настройки
только про сам вызов.
"""

from __future__ import annotations

import copy
import os
from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .errors import ConfigError

APP_NAME = "llmkit"

# Дефолты настроек — бывшие значения config.toml с Mac (0.8.1); переопределяются
# аргументами LlmKit(...), флагами CLI и LLMKIT_LOG_LEVEL.
DEFAULTS: dict[str, Any] = {
    "defaults": {"temperature": 0.0, "timeout": 120.0, "max_tokens": 16000, "concurrency": 6},
}


class Defaults(BaseModel):
    model_config = ConfigDict(extra="forbid")

    temperature: float = 0.0
    timeout: float = 120.0
    max_tokens: int = 16000
    concurrency: int = 6


class RetryConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # timeout 0 — без повтора на той же модели: сразу следующая (не ждать 2× таймаут на застрявшем шлюзе);
    # rate_limit/server 6 — шлюзы просят повтор через ~60 с, пауза до 30 с ×6 ≈ 3 мин (config.toml с Mac).
    timeout: int = 0
    rate_limit: int = 6
    server: int = 6
    invalid_output: int = 2


class Config(BaseModel):
    """Настройки вызовов (не провайдеры: они в routing)."""

    model_config = ConfigDict(extra="forbid")

    defaults: Defaults = Field(default_factory=Defaults)
    retry: RetryConfig = Field(default_factory=RetryConfig)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] | None = None


def merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    """Рекурсивное слияние словарей: списки и скаляры перекрываются целиком."""
    result = dict(base)
    for key, value in over.items():
        current = result.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            result[key] = merge(current, value)
        else:
            result[key] = value
    return result


def env_layer(env: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Скалярные переопределения из env (раздел 3 спецификации)."""
    env = os.environ if env is None else env
    layer: dict[str, Any] = {}
    if env.get("LLMKIT_LOG_LEVEL"):
        layer["log_level"] = env["LLMKIT_LOG_LEVEL"].upper()
    return layer


def load(*, overrides: dict[str, Any] | None = None, env: Mapping[str, str] | None = None) -> Config:
    """Настройки: дефолты в коде → env → `overrides` (аргументы `LlmKit(...)`)."""
    data: dict[str, Any] = {}
    for layer in [copy.deepcopy(DEFAULTS), env_layer(env), overrides or {}]:
        data = merge(data, layer)
    try:
        return Config.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(f"настройки не проходят проверку: {exc}") from exc
