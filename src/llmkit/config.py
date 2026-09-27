"""Конфиг: модели, загрузка файлов, слияние слоёв.

Порядок слияния (позже перекрывает раньше): дефолты в коде →
`~/.config/llmkit/config.toml` → `.llmkit/config.toml` проекта (поиск вверх от
cwd) → env `LLMKIT_*` → аргументы `LlmKit(...)`. Если задан `LLMKIT_CONFIG`,
он заменяет поиск файлов: читается только указанный файл.
"""

from __future__ import annotations

import copy
import os
import re
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from .errors import ConfigError

APP_NAME = "llmkit"

# Имя метки: только то, что безопасно подставить в json_extract(tags, '$.имя').
TAG_NAME_RE = re.compile(r"^[A-Za-z0-9_]+$")

# Провайдер и уровни «из коробки»: без своего конфига kit всё равно работает.
DEFAULTS: dict[str, Any] = {
    "providers": {
        "openrouter": {"kind": "openrouter"},
        "ollama": {"kind": "ollama", "base_url": "https://ollama.com"},
        # Ccode (ccode.dev): OpenAI-совместимый шлюз к моделям разных вендоров.
        "ccode": {
            "kind": "openai_compatible",
            "base_url": "https://all-api.ccode.dev/v1",
            "api_key_env": "CCODE_API_KEY",
            # Вызовы инструментов шлюз поддерживает для всех вендоров, json_object — не гарантирован.
            "mode": "TOOLS",
        },
        # Подписки: вход через `llm auth login <провайдер>`, ключ не нужен.
        "chatgpt": {"kind": "chatgpt", "requires_key": False},
        "claude": {"kind": "claude_cli", "requires_key": False},
    },
    # Цепочки — пример: модели каждый подбирает под себя, формат
    # "провайдер/модель", где провайдер — ключ из [providers].
    "levels": {
        "cheap": ["ollama/gpt-oss:120b", "openrouter/openai/gpt-4o-mini"],
        "judge": ["openrouter/anthropic/claude-sonnet-4", "openrouter/openai/gpt-4o"],
        "strong": ["openrouter/anthropic/claude-opus-4"],
    },
    "budget": {"daily_usd": 20.0},
}


class Price(BaseModel):
    """Цена модели в $ за 1M токенов — если LiteLLM её не знает."""

    model_config = ConfigDict(extra="forbid")

    input: float = 0.0
    output: float = 0.0


class ProviderConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str
    base_url: str | None = None
    api_key: str | None = None  # не рекомендуется: ключ в файле конфига
    api_key_env: str | None = None
    requires_key: bool = True
    mode: str | None = None  # режим Instructor: TOOLS | JSON
    prices: dict[str, Price] = Field(default_factory=dict)


class Defaults(BaseModel):
    model_config = ConfigDict(extra="forbid")

    level: str = "cheap"
    temperature: float = 0.0
    timeout: float = 120.0
    max_tokens: int = 4096
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

    daily_usd: float | None = None
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

    timeout: int = 1
    rate_limit: int = 2
    server: int = 2
    invalid_output: int = 2


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid")

    providers: dict[str, ProviderConfig] = Field(default_factory=dict)
    levels: dict[str, list[str]] = Field(default_factory=dict)
    defaults: Defaults = Field(default_factory=Defaults)
    cache: CacheConfig = Field(default_factory=CacheConfig)
    usage: UsageConfig = Field(default_factory=UsageConfig)
    budget: BudgetConfig = Field(default_factory=BudgetConfig)
    retry: RetryConfig = Field(default_factory=RetryConfig)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] | None = None

    def provider(self, name: str) -> ProviderConfig:
        try:
            return self.providers[name]
        except KeyError:
            known = ", ".join(sorted(self.providers)) or "нет ни одного"
            raise ConfigError(f"неизвестный провайдер {name!r}; известные: {known}") from None

    def chain_for(self, level: str) -> list[str]:
        try:
            return list(self.levels[level])
        except KeyError:
            known = ", ".join(sorted(self.levels)) or "нет ни одного"
            raise ConfigError(f"неизвестный уровень {level!r}; уровни: {known}") from None

    def check_levels(self) -> None:
        """Все цепочки ссылаются на описанных провайдеров."""
        known = ", ".join(sorted(self.providers)) or "нет ни одного"
        for level, chain in self.levels.items():
            for ref in chain:
                provider, _, model = ref.partition("/")
                if not model:
                    raise ConfigError(f"уровень {level!r}: модель {ref!r} должна быть вида 'провайдер/модель'")
                if provider not in self.providers:
                    raise ConfigError(
                        f"уровень {level!r} ссылается на провайдера {provider!r} ({ref}), "
                        f"которого нет в [providers]; описанные провайдеры: {known}"
                    )

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


def user_config_path() -> Path:
    import platformdirs

    return Path(platformdirs.user_config_dir(APP_NAME)) / "config.toml"


def project_config_path(start: Path | None = None) -> Path | None:
    """Ближайший `.llmkit/config.toml` вверх от cwd."""
    current = (start or Path.cwd()).resolve()
    for directory in [current, *current.parents]:
        candidate = directory / ".llmkit" / "config.toml"
        if candidate.is_file():
            return candidate
    return None


def read_toml(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except OSError as exc:
        raise ConfigError(f"не читается конфиг {path}: {exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"битый TOML в {path}: {exc}") from exc


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


def layers(env: Mapping[str, str] | None = None) -> list[dict[str, Any]]:
    """Слои конфига по порядку применения."""
    env = os.environ if env is None else env
    result = [copy.deepcopy(DEFAULTS)]
    explicit = env.get("LLMKIT_CONFIG")
    if explicit:
        path = _expand(Path(explicit))
        if not path.is_file():
            raise ConfigError(f"LLMKIT_CONFIG указывает на несуществующий файл: {path}")
        result.append(read_toml(path))
    else:
        user = user_config_path()
        if user.is_file():
            result.append(read_toml(user))
        project = project_config_path()
        if project is not None:
            result.append(read_toml(project))
    result.append(env_layer(env))
    return result


def load(*, overrides: dict[str, Any] | None = None, env: dict[str, str] | None = None) -> Config:
    """Собрать конфиг из всех слоёв; `overrides` — аргументы `LlmKit(...)`."""
    data: dict[str, Any] = {}
    for layer in [*layers(env), overrides or {}]:
        data = merge(data, layer)
    try:
        return Config.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(f"конфиг не проходит проверку: {exc}") from exc
