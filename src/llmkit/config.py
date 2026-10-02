"""Настройки вызовов: дефолты в коде → env `LLMKIT_*` → аргументы `LlmKit(...)`.

С 0.8.0 файлов конфига нет: провайдеры, цепочка и цены приходят данными
(routing v1, `routing.py`). `config.toml` прошлых версий не читается —
перенести его: `llm routing import <config.toml>`.
"""

from __future__ import annotations

import copy
import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from .errors import ConfigError

APP_NAME = "llmkit"

# Имя метки: только то, что безопасно подставить в json_extract(tags, '$.имя').
TAG_NAME_RE = re.compile(r"^[A-Za-z0-9_]+$")

# Дефолты настроек — бывшие значения config.toml с Mac (0.8.1); переопределяются
# аргументами LlmKit(...), флагами CLI и LLMKIT_CACHE / LLMKIT_LOG_LEVEL.
DEFAULTS: dict[str, Any] = {
    "defaults": {"temperature": 0.0, "timeout": 120.0, "max_tokens": 16000, "concurrency": 6},
    "budget": {"daily_usd": 20.0},
}


class Defaults(BaseModel):
    model_config = ConfigDict(extra="forbid")

    temperature: float = 0.0
    timeout: float = 120.0
    max_tokens: int = 16000
    concurrency: int = 6


class CacheConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    ttl_days: int = Field(default=30, ge=1)  # 0 означал бы «кэш навсегда» — это делает enabled
    path: Path | None = None


class UsageConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: Path | None = None


class BudgetConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    daily_usd: float | None = 20.0
    tags: dict[str, float] = Field(default_factory=dict)

    @field_validator("tags")
    @classmethod
    def _check_tag_keys(cls, value: dict[str, float]) -> dict[str, float]:
        for key in value:
            name, sep, _ = key.partition("=")
            if not sep or not TAG_NAME_RE.match(name):
                raise ValueError(f"ключ бюджета должен быть вида 'метка=значение' с именем [A-Za-z0-9_]: {key!r}")
        return value


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
    cache: CacheConfig = Field(default_factory=CacheConfig)
    usage: UsageConfig = Field(default_factory=UsageConfig)
    budget: BudgetConfig = Field(default_factory=BudgetConfig)
    retry: RetryConfig = Field(default_factory=RetryConfig)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] | None = None

    def cache_path(self) -> Path:
        return _expand(self.cache.path) if self.cache.path else _user_dir("cache") / "cache.sqlite"

    def usage_path(self) -> Path:
        return _expand(self.usage.path) if self.usage.path else _user_dir("data") / "usage.sqlite"


def _expand(path: Path) -> Path:
    return Path(os.path.expandvars(str(path))).expanduser()


def _user_dir(which: str) -> Path:
    import platformdirs

    fn = platformdirs.user_cache_dir if which == "cache" else platformdirs.user_data_dir
    return Path(fn(APP_NAME))


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
    raw_cache = env.get("LLMKIT_CACHE", "").strip()
    if raw_cache:  # пустое значение — как будто переменной нет
        layer["cache"] = {"enabled": raw_cache.lower() not in ("0", "false", "no")}
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
