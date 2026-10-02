"""Ключи провайдеров: `key_env` (по умолчанию LLM_<ПРОВАЙДЕР>_API_KEY) → старое имя → связка ключей ОС.

Старые имена (OPENROUTER_API_KEY, CCODE_API_KEY…) работают один цикл с
предупреждением «rename to LLM_…». Связка: `keyring.get_password("llmkit:<provider>",
"<provider>")`, значение — JSON `{"api_key": "..."}`. Ключи только читаются;
`store()` вызывает CLI. В лог, ответ и журнал ключи не попадают никогда.
"""

from __future__ import annotations

import json
import logging
import os
import re
from collections.abc import Mapping

from .config import APP_NAME
from .errors import KeyMissing
from .routing import Provider

log = logging.getLogger(__name__)

# Имена ключей до 0.8.0 по протоколу; иначе <ПРОВАЙДЕР>_API_KEY.
LEGACY_ENV_BY_PROTOCOL = {
    "openrouter": "OPENROUTER_API_KEY",
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "ollama": "OLLAMA_API_KEY",
}

_store_warned = False


def service_name(provider: str) -> str:
    return f"{APP_NAME}:{provider}"


def _upper(provider: str) -> str:
    return re.sub(r"[^A-Z0-9]", "_", provider.upper())


def default_env(provider: str) -> str:
    """Имя переменной ключа по умолчанию: LLM_<ПРОВАЙДЕР>_API_KEY."""
    return f"LLM_{_upper(provider)}_API_KEY"


def env_var(provider: str, cfg: Provider) -> str:
    return cfg.key_env or default_env(provider)


def legacy_env(provider: str, cfg: Provider) -> str:
    """Имя ключа до 0.8.0 — читается один цикл с предупреждением."""
    return LEGACY_ENV_BY_PROTOCOL.get(cfg.protocol) or f"{_upper(provider)}_API_KEY"


def from_keychain(provider: str) -> str | None:
    """Ключ из связки ключей; недоступная связка — предупреждение и None."""
    global _store_warned
    import keyring
    import keyring.errors

    try:
        raw = keyring.get_password(service_name(provider), provider)
    except keyring.errors.KeyringError as exc:
        if not _store_warned:
            log.warning("связка ключей недоступна (%s); используются только переменные окружения", exc)
            _store_warned = True
        return None
    if not raw:
        return None
    try:
        return json.loads(raw).get("api_key") or None
    except (ValueError, AttributeError):
        # Старое значение в виде голой строки — принимаем как есть.
        return raw or None


def resolve(
    provider: str, cfg: Provider, *, env: Mapping[str, str] | None = None, warnings: list[str] | None = None
) -> str | None:
    """Ключ провайдера; подпискам ключ не нужен (None). Старое имя — с предупреждением в `warnings`."""
    if cfg.subscription:
        return None
    env = os.environ if env is None else env
    name = env_var(provider, cfg)
    value = env.get(name)
    if value:
        return value
    legacy = legacy_env(provider, cfg)
    if legacy != name and env.get(legacy):
        message = f"key from {legacy}: rename to {name}"
        log.warning("%s", message)
        if warnings is not None:
            warnings.append(message)
        return env[legacy]
    value = from_keychain(provider)
    if value:
        return value
    raise KeyMissing(provider, name)


def store(provider: str, api_key: str) -> None:
    """Положить ключ в связку ключей ОС."""
    import keyring

    keyring.set_password(service_name(provider), provider, json.dumps({"api_key": api_key}))


def delete(provider: str) -> None:
    """Удалить ключ из связки; отсутствующий ключ — не ошибка."""
    import contextlib

    import keyring
    import keyring.errors

    with contextlib.suppress(keyring.errors.PasswordDeleteError):
        keyring.delete_password(service_name(provider), provider)
