"""Ключи провайдеров: аргумент конфига → env → связка ключей ОС.

Связка: `keyring.get_password("llmkit:<provider>", "<provider>")`, значение —
JSON `{"api_key": "..."}` (та же форма, что у остальных инструментов). Ключи
только читаются; `store()` вызывает CLI. В лог ключи не попадают никогда.
"""

from __future__ import annotations

import json
import logging
import os

from .config import APP_NAME, ProviderConfig
from .errors import KeyMissing

log = logging.getLogger(__name__)

# Стандартное env-имя ключа по виду провайдера; `api_key_env` перекрывает.
ENV_BY_KIND = {
    "openrouter": "OPENROUTER_API_KEY",
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "ollama": "OLLAMA_API_KEY",
}

_store_warned = False


def service_name(provider: str) -> str:
    return f"{APP_NAME}:{provider}"


def env_var(provider: str, cfg: ProviderConfig) -> str:
    return cfg.api_key_env or ENV_BY_KIND.get(cfg.kind, f"{provider.upper()}_API_KEY")


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


def resolve(provider: str, cfg: ProviderConfig, *, env: dict[str, str] | None = None) -> str | None:
    """Ключ провайдера или None, если провайдеру ключ не нужен."""
    env = os.environ if env is None else env
    if cfg.api_key:
        return cfg.api_key
    name = env_var(provider, cfg)
    value = env.get(name)
    if value:
        return value
    value = from_keychain(provider)
    if value:
        return value
    if cfg.requires_key:
        raise KeyMissing(provider, name)
    return None


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
