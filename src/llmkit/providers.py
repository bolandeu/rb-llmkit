"""Описание провайдера → аргументы вызова LiteLLM (таблица раздела 3 спеки)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import keys
from .config import Config, ProviderConfig
from .errors import ConfigError

# kind → (префикс модели для litellm, нужен ли api_base)
KINDS = {
    "openrouter": ("openrouter/", False),
    "openai": ("", False),
    "anthropic": ("anthropic/", False),
    "gemini": ("gemini/", False),
    "ollama": ("ollama_chat/", True),
    "openai_compatible": ("openai/", True),
}

# Режим Instructor по виду провайдера; `mode` в конфиге перекрывает.
_JSON_MODE_KINDS = frozenset({"ollama", "openai_compatible"})


@dataclass(frozen=True)
class ModelCall:
    """Всё, что нужно для одного вызова модели."""

    ref: str  # "provider/model" из конфига
    provider: str
    model: str  # имя модели у провайдера
    litellm_model: str
    mode: str  # режим Instructor: TOOLS | JSON
    params: dict[str, Any] = field(default_factory=dict)


def split_ref(ref: str) -> tuple[str, str]:
    """`"openrouter/openai/gpt-4o-mini"` → `("openrouter", "openai/gpt-4o-mini")`."""
    provider, _, model = ref.partition("/")
    if not provider or not model:
        raise ConfigError(f"ссылка на модель должна иметь вид 'provider/model', получено {ref!r}")
    return provider, model


def instructor_mode(cfg: ProviderConfig) -> str:
    if cfg.mode:
        return cfg.mode.upper()
    return "JSON" if cfg.kind in _JSON_MODE_KINDS else "TOOLS"


def build(ref: str, config: Config, *, env: dict[str, str] | None = None) -> ModelCall:
    """Собрать вызов по ссылке `provider/model`; может бросить `KeyMissing`."""
    provider, model = split_ref(ref)
    cfg = config.provider(provider)
    try:
        prefix, needs_base = KINDS[cfg.kind]
    except KeyError:
        raise ConfigError(f"неизвестный kind провайдера {provider}: {cfg.kind!r}") from None

    params: dict[str, Any] = {}
    api_key = keys.resolve(provider, cfg, env=env)
    if api_key:
        params["api_key"] = api_key
    if needs_base:
        if not cfg.base_url:
            raise ConfigError(f"провайдеру {provider} (kind={cfg.kind}) нужен base_url в конфиге")
        params["api_base"] = cfg.base_url
    return ModelCall(
        ref=ref,
        provider=provider,
        model=model,
        litellm_model=f"{prefix}{model}",
        mode=instructor_mode(cfg),
        params=params,
    )


def price_from_config(config: Config, call: ModelCall, prompt_tokens: int, completion_tokens: int) -> float | None:
    """Стоимость по `providers.<p>.prices[model]` ($ за 1M токенов)."""
    price = config.provider(call.provider).prices.get(call.model)
    if price is None:
        return None
    return (prompt_tokens * price.input + completion_tokens * price.output) / 1_000_000
