"""Ключ шлюза: llmkit знает только имя переменной (`key_env` провайдера routing).

Своего хранилища у llmkit нет: ни связки ключей, ни старых имён переменных.
Значение приходит из окружения процесса; сам ключ никуда не пишется и не
печатается — он нужен только заголовку запроса к шлюзу.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping

from .errors import KeyMissing
from .routing import Provider


def _upper(provider: str) -> str:
    return re.sub(r"[^A-Z0-9]", "_", provider.upper())


def default_env(provider: str) -> str:
    """Имя переменной ключа по умолчанию: LLM_<ПРОВАЙДЕР>_API_KEY."""
    return f"LLM_{_upper(provider)}_API_KEY"


def env_var(provider: str, cfg: Provider) -> str:
    return cfg.key_env or default_env(provider)


def resolve(provider: str, cfg: Provider, *, env: Mapping[str, str] | None = None) -> str:
    """Ключ шлюза из окружения; переменной нет — `KeyMissing` с её именем."""
    env = os.environ if env is None else env
    name = env_var(provider, cfg)
    value = env.get(name)
    if value:
        return value
    raise KeyMissing(provider, name)
