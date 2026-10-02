"""Провайдер из routing → аргументы вызова LiteLLM (таблица раздела 3 спеки)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from . import keys
from .errors import LoginMissing, RoutingInvalid
from .routing import SUBSCRIPTION_PROTOCOLS, Provider, Routing

# protocol → (префикс модели для litellm, нужен ли api_base)
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
SUBSCRIPTION_KINDS = SUBSCRIPTION_PROTOCOLS

# Режим Instructor по протоколу; `mode` в routing перекрывает.
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

    ref: str  # "provider/model" из routing
    provider: str
    model: str  # имя модели у провайдера
    litellm_model: str
    mode: str  # режим Instructor: TOOLS | JSON
    # repr=False: в params лежит api_key, он не должен попасть в лог или traceback.
    params: dict[str, Any] = field(default_factory=dict, repr=False)
    # Свой вызов модели вместо litellm.acompletion (провайдеры по подписке).
    completion: Callable[..., Any] | None = field(default=None, repr=False)
    subscription: bool = False
    # Предупреждения резолва (ключ из старой переменной) — в ответ задачи.
    warnings: tuple[str, ...] = ()


def split_ref(ref: str) -> tuple[str, str]:
    """`"openrouter/openai/gpt-4o-mini"` → `("openrouter", "openai/gpt-4o-mini")`."""
    provider, _, model = ref.partition("/")
    if not provider or not model:
        raise RoutingInvalid("/chain", f"ссылка на модель должна иметь вид 'provider/model', получено {ref!r}")
    return provider, model


def instructor_mode(cfg: Provider) -> str:
    if cfg.mode:
        return cfg.mode.upper()
    return _MODE_BY_KIND.get(cfg.protocol, "TOOLS")


def api_base(ref: str, routing: Routing) -> str | None:
    """Адрес провайдера без резолва ключа — нужен для ключа кэша."""
    provider, _ = split_ref(ref)
    cfg = routing.provider(provider)
    _, needs_base = KINDS[cfg.protocol]
    return cfg.base_url if needs_base else None


def build(ref: str, routing: Routing, *, env: dict[str, str] | None = None) -> ModelCall:
    """Собрать вызов по ссылке `provider/model`; может бросить `KeyMissing`."""
    provider, model = split_ref(ref)
    cfg = routing.provider(provider)
    prefix, needs_base = KINDS[cfg.protocol]
    if cfg.subscription:
        return _subscription_call(ref, provider, model, cfg, env)

    params: dict[str, Any] = {}
    warnings: list[str] = []
    api_key = keys.resolve(provider, cfg, env=env, warnings=warnings)
    if api_key:
        params["api_key"] = api_key
    if needs_base:
        params["api_base"] = cfg.base_url
    return ModelCall(
        ref=ref,
        provider=provider,
        model=model,
        litellm_model=f"{prefix}{model}",
        mode=instructor_mode(cfg),
        params=params,
        warnings=tuple(warnings),
    )


def _subscription_call(ref: str, provider: str, model: str, cfg: Provider, env: dict[str, str] | None) -> ModelCall:
    """Провайдер по подписке: проверить вход здесь, чтобы не падать в сети."""
    params: dict[str, Any] = {"provider": provider}
    if cfg.protocol == "chatgpt":
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


def price_from_routing(routing: Routing, call: ModelCall, prompt_tokens: int, completion_tokens: int) -> float | None:
    """Стоимость по `routing.prices["провайдер/модель"]` ($ за 1M токенов)."""
    price = routing.prices.get(call.ref)
    if price is None:
        return None
    return (prompt_tokens * price.input + completion_tokens * price.output) / 1_000_000
