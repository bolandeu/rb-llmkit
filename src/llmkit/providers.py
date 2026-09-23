"""Описание провайдера → аргументы вызова LiteLLM (таблица раздела 3 спеки)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from . import keys
from .config import Config, ProviderConfig
from .errors import ConfigError, LoginMissing

# kind → (префикс модели для litellm, нужен ли api_base)
KINDS = {
    "openrouter": ("openrouter/", False),
    "openai": ("", False),
    "anthropic": ("anthropic/", False),
    "gemini": ("gemini/", False),
    "ollama": ("ollama_chat/", True),
    "openai_compatible": ("openai/", True),
    "chatgpt": ("", False),
    "claude_cli": ("", False),
}

# Провайдеры по подписке: свой транспорт вместо LiteLLM, вход вместо ключа, цена 0.
SUBSCRIPTION_KINDS = frozenset({"chatgpt", "claude_cli"})

# Режим Instructor по виду провайдера; `mode` в конфиге перекрывает.
# Подписки отдают схему нативно (text.format / --json-schema) — JSON_SCHEMA.
_MODE_BY_KIND = {
    "ollama": "JSON",
    "openai_compatible": "JSON",
    "chatgpt": "JSON_SCHEMA",
    "claude_cli": "JSON_SCHEMA",
}


@dataclass(frozen=True)
class ModelCall:
    """Всё, что нужно для одного вызова модели."""

    ref: str  # "provider/model" из конфига
    provider: str
    model: str  # имя модели у провайдера
    litellm_model: str
    mode: str  # режим Instructor: TOOLS | JSON
    # repr=False: в params лежит api_key, он не должен попасть в лог или traceback.
    params: dict[str, Any] = field(default_factory=dict, repr=False)
    # Свой вызов модели вместо litellm.acompletion (провайдеры по подписке).
    completion: Callable[..., Any] | None = field(default=None, repr=False)
    subscription: bool = False


def split_ref(ref: str) -> tuple[str, str]:
    """`"openrouter/openai/gpt-4o-mini"` → `("openrouter", "openai/gpt-4o-mini")`."""
    provider, _, model = ref.partition("/")
    if not provider or not model:
        raise ConfigError(f"ссылка на модель должна иметь вид 'provider/model', получено {ref!r}")
    return provider, model


def instructor_mode(cfg: ProviderConfig) -> str:
    if cfg.mode:
        return cfg.mode.upper()
    return _MODE_BY_KIND.get(cfg.kind, "TOOLS")


def api_base(ref: str, config: Config) -> str | None:
    """Адрес провайдера без резолва ключа — нужен для ключа кэша."""
    provider, _ = split_ref(ref)
    cfg = config.provider(provider)
    _, needs_base = KINDS.get(cfg.kind, ("", False))
    return cfg.base_url if needs_base else None


def build(ref: str, config: Config, *, env: dict[str, str] | None = None) -> ModelCall:
    """Собрать вызов по ссылке `provider/model`; может бросить `KeyMissing`."""
    provider, model = split_ref(ref)
    cfg = config.provider(provider)
    try:
        prefix, needs_base = KINDS[cfg.kind]
    except KeyError:
        raise ConfigError(f"неизвестный kind провайдера {provider}: {cfg.kind!r}") from None
    if cfg.kind in SUBSCRIPTION_KINDS:
        return _subscription_call(ref, provider, model, cfg, env)

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


def _subscription_call(
    ref: str, provider: str, model: str, cfg: ProviderConfig, env: dict[str, str] | None
) -> ModelCall:
    """Провайдер по подписке: проверить вход здесь, чтобы не падать в сети."""
    params: dict[str, Any] = {"provider": provider}
    if cfg.kind == "chatgpt":
        from .transports import chatgpt, chatgpt_auth

        path = chatgpt_auth.default_path()
        if chatgpt_auth.read_auth(path) is None:
            raise LoginMissing(provider, chatgpt_auth.login_hint(provider))
        params["auth_file"] = str(path)
        if cfg.base_url:
            params["api_base"] = cfg.base_url
        completion = chatgpt.acompletion
    else:
        from .transports import claude_cli

        if claude_cli.command(env) is None:
            raise LoginMissing(provider, "установите Claude Code CLI и выполните `claude auth login`")
        completion = claude_cli.acompletion
    return ModelCall(
        ref=ref,
        provider=provider,
        model=model,
        litellm_model=model,
        mode=instructor_mode(cfg),
        params=params,
        completion=completion,
        subscription=True,
    )


def price_from_config(config: Config, call: ModelCall, prompt_tokens: int, completion_tokens: int) -> float | None:
    """Стоимость по `providers.<p>.prices[model]` ($ за 1M токенов)."""
    price = config.provider(call.provider).prices.get(call.model)
    if price is None:
        return None
    return (prompt_tokens * price.input + completion_tokens * price.output) / 1_000_000
