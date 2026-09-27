"""Здоровье доступов: отчёт `llm auth status [--check]` (tools/docs/standard-release.md §8).

Форма отчёта — общий контракт инструментов (`tools-watch` читает её, не
зная провайдеров), её фиксирует `tests/test_health.py`; изменение формы —
ломающее изменение. Значения ключей и токенов наружу не выходят: они нужны
только чтобы вычистить их из сообщений.

Без `check` отчёт только про наличие доступа (`unchecked` / `missing`).
С `check` у каждого провайдера один дешёвый вызов без списания денег,
жёсткий лимит 10 с, без повторов.
"""

from __future__ import annotations

import concurrent.futures
import os
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from . import keys
from .config import Config, ProviderConfig
from .providers import SUBSCRIPTION_KINDS
from .version import installed_version

TOOL = "llmkit"
CHECK_TIMEOUT = 10.0
# Проблема даже у необязательного провайдера: доступ есть, но неверный.
ALWAYS_PROBLEMS = frozenset({"invalid", "expired"})
HEALTHY = frozenset({"ok", "unchecked"})

# Дешёвый read-only вызов по виду провайдера: (метод, адрес, заголовки с ключом).
# У ollama.com список моделей открыт без ключа, ключ проверяет только /api/me.
_KEY_CHECKS: dict[str, Callable[[str, str | None], tuple[str, str, dict[str, str]]]] = {
    "openrouter": lambda key, base: ("GET", "https://openrouter.ai/api/v1/key", {"Authorization": f"Bearer {key}"}),
    "openai": lambda key, base: ("GET", "https://api.openai.com/v1/models", {"Authorization": f"Bearer {key}"}),
    "anthropic": lambda key, base: (
        "GET",
        "https://api.anthropic.com/v1/models",
        {"x-api-key": key, "anthropic-version": "2023-06-01"},
    ),
    "gemini": lambda key, base: (
        "GET",
        "https://generativelanguage.googleapis.com/v1beta/models",
        {"x-goog-api-key": key},
    ),
    "ollama": lambda key, base: (
        "POST",
        f"{(base or 'https://ollama.com').rstrip('/')}/api/me",
        {"Authorization": f"Bearer {key}"},
    ),
    "openai_compatible": lambda key, base: (
        "GET",
        f"{(base or '').rstrip('/')}/models",
        {"Authorization": f"Bearer {key}"},
    ),
}


@dataclass
class Health:
    """Итог проверки одного провайдера."""

    status: str = "ok"
    expires_at: datetime | None = None
    quota: dict[str, Any] | None = None
    message: str | None = None


def _now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def _iso(moment: datetime | None) -> str | None:
    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z") if moment else None


def _scrub(message: str | None, secrets: list[str]) -> str | None:
    if message is None:
        return None
    for secret in secrets:
        if secret:
            message = message.replace(secret, "***")
    return message


def _version() -> str:
    return installed_version() or "0.0.0"  # запуск из исходников без установки


def _with_timeout(check: Callable[[], Health]) -> Health:
    """Жёсткий лимит на всю проверку, что бы ни делала она внутри."""
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        return pool.submit(check).result(timeout=CHECK_TIMEOUT)
    except concurrent.futures.TimeoutError:
        return Health("unreachable", message=f"нет ответа за {CHECK_TIMEOUT:g} с")
    except Exception as exc:
        return Health("unreachable", message=f"{type(exc).__name__}: {exc}")
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


# --- ключи API ------------------------------------------------------------------


def _openrouter_quota(body: Any) -> dict[str, Any] | None:
    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, dict):
        return None
    return {"remaining": data.get("limit_remaining"), "limit": data.get("limit"), "unit": "usd"}


def check_key(kind: str, api_key: str, base_url: str | None, *, transport: Any = None) -> Health:
    """Один дешёвый вызов с ключом: 401/403 — invalid, 429/5xx/сеть — unreachable."""
    import httpx

    make = _KEY_CHECKS.get(kind)
    if make is None:
        return Health("unchecked", message=f"для kind={kind} проверки нет")
    method, url, headers = make(api_key, base_url)
    try:
        with httpx.Client(timeout=CHECK_TIMEOUT, transport=transport) as client:
            response = client.request(method, url, headers=headers)
    except httpx.HTTPError as exc:
        return Health("unreachable", message=f"{type(exc).__name__}: {exc}")
    if response.status_code in (401, 403):
        return Health("invalid", message=f"провайдер отверг ключ (HTTP {response.status_code})")
    if response.status_code == 429:
        return Health("unreachable", message="лимит запросов (HTTP 429), повторите позже")
    if response.status_code >= 400:
        return Health("unreachable", message=f"HTTP {response.status_code}")
    if kind == "openrouter":
        try:
            quota = _openrouter_quota(response.json())
        except ValueError:
            quota = None
        if quota and quota["remaining"] is not None and quota["remaining"] <= 0:
            return Health("quota_exhausted", quota=quota, message="лимит ключа OpenRouter исчерпан")
        return Health(quota=quota)
    return Health()


def _key_entry(name: str, cfg: ProviderConfig, check: bool, env: Mapping[str, str]) -> dict[str, Any]:
    env_name = keys.env_var(name, cfg)
    keychain_ref = f"keychain service {keys.service_name(name)}"
    entry = _blank(name, ["api_key"], f"{env_name} or {keychain_ref}")
    if cfg.api_key:  # порядок как в keys.resolve: конфиг → env → связка
        value, source, ref = cfg.api_key, "file", f"providers.{name}.api_key в конфиге (`llm config path`)"
    elif env.get(env_name):
        value, source, ref = env[env_name], "env", env_name
    elif found := keys.from_keychain(name):
        value, source, ref = found, "keychain", keychain_ref
    else:
        entry["message"] = f"`llm keys set {name}` или `export {env_name}=...`"
        return entry
    entry.update(source=source, source_ref=ref)
    if not check:
        entry["status"] = "unchecked"
        return entry
    return _apply(entry, _with_timeout(lambda: check_key(cfg.kind, value, cfg.base_url)), [value])


# --- подписки -------------------------------------------------------------------


def _chatgpt_entry(name: str, check: bool) -> dict[str, Any]:
    from .transports import chatgpt_auth

    path = chatgpt_auth.default_path()
    entry = _blank(name, ["access_token", "refresh_token"], str(path))
    auth = chatgpt_auth.read_auth(path)
    if auth is None:
        entry["message"] = chatgpt_auth.login_hint(name)
        return entry
    entry.update(source="file", message=f"план: {auth.plan_type}" if auth.plan_type else None)
    if not check:
        entry["status"] = "unchecked"
        return entry
    secrets = [auth.access_token, auth.refresh_token or ""]
    return _apply(entry, _with_timeout(lambda: _check_chatgpt(name, path)), secrets)


def _check_chatgpt(name: str, path: Any) -> Health:
    """Свежий access-токен, обновлённый при нужде тем же путём, что и перед вызовом модели.

    Обновление бесплатное; модель не вызывается, так что квоту подписки
    проверка не тратит. Свежий токен без обновления сервер не спрашивает.
    """
    import asyncio

    import httpx

    from .transports import chatgpt_auth

    async def access() -> chatgpt_auth.Auth:
        async with httpx.AsyncClient(timeout=CHECK_TIMEOUT) as client:
            return await chatgpt_auth.store_for(path, name).access(client)

    try:
        auth = asyncio.run(access())
    except chatgpt_auth.SubscriptionAuthError as exc:
        return Health("invalid", message=str(exc))
    except httpx.HTTPError as exc:
        return Health("unreachable", message=f"{type(exc).__name__}: {exc}")
    plan = f"план: {auth.plan_type}; " if auth.plan_type else ""
    return Health(message=f"{plan}access-токен действителен, при истечении обновляется сам")


def _claude_entry(name: str, check: bool) -> dict[str, Any]:
    import asyncio

    from .transports import claude_cli

    # Вход хранит сам `claude`: на macOS в связке ключей, на Linux в ~/.claude.
    source = "keychain" if sys.platform == "darwin" else "file"
    entry = _blank(name, ["login"], "вход `claude` CLI (`claude auth status`)")
    timeout = CHECK_TIMEOUT if check else 20.0
    status = asyncio.run(claude_cli.auth_status(timeout=timeout))
    if not status["installed"]:
        entry["message"] = "CLI `claude` не найден: установите Claude Code"
        return entry
    if not status["loggedIn"]:
        entry["message"] = status.get("error") or "выполните `claude auth login`"
        if check and status.get("error"):
            entry.update(source=source, status="unreachable")
        return entry
    parts = [str(status[k]) for k in ("authMethod", "subscriptionType") if status.get(k)]
    if check:
        parts.append("проверено локально (`claude auth status`), модель не вызывалась")
    entry.update(source=source, status="ok" if check else "unchecked", message="; ".join(parts) or None)
    return entry


# --- отчёт ----------------------------------------------------------------------


def _blank(name: str, fields: list[str], source_ref: str) -> dict[str, Any]:
    return {
        "provider": name,
        # llmkit работает с любым подмножеством провайдеров конфига — обязательных нет.
        "required": False,
        "fields": fields,
        "source": "missing",
        "source_ref": source_ref,
        "status": "missing",
        "expires_at": None,
        "quota": None,
        "message": None,
    }


def _apply(entry: dict[str, Any], health: Health, secrets: list[str]) -> dict[str, Any]:
    status = health.status
    if status == "ok" and health.expires_at and health.expires_at <= _now():
        status = "expired"
    entry.update(
        status=status,
        expires_at=_iso(health.expires_at),
        quota=health.quota,
        message=_scrub(health.message, secrets) if health.message else entry["message"],
    )
    return entry


def has_credentials(cfg: ProviderConfig) -> bool:
    """Провайдеры без доступа (локальный ollama с requires_key=false) в отчёт не попадают."""
    return cfg.kind in SUBSCRIPTION_KINDS or cfg.requires_key


def credential_entry(
    name: str, cfg: ProviderConfig, *, check: bool, env: Mapping[str, str] | None = None
) -> dict[str, Any]:
    """Строка отчёта §8 для одного провайдера."""
    if cfg.kind == "chatgpt":
        return _chatgpt_entry(name, check)
    if cfg.kind == "claude_cli":
        return _claude_entry(name, check)
    return _key_entry(name, cfg, check, os.environ if env is None else env)


def report(config: Config, *, check: bool, only: str | None = None) -> dict[str, Any]:
    """Отчёт §8 по провайдерам конфига (или по одному, `only`)."""
    return {
        "tool": TOOL,
        "version": _version(),
        "checked_at": _iso(_now()),
        "credentials": [
            credential_entry(name, cfg, check=check)
            for name, cfg in sorted(config.providers.items())
            if has_credentials(cfg) and (only is None or name == only)
        ],
    }


def is_problem(item: dict[str, Any]) -> bool:
    """Код выхода 3: неверный/просроченный доступ у любого, иная беда — у обязательного."""
    if item["status"] in ALWAYS_PROBLEMS:
        return True
    return bool(item["required"]) and item["status"] not in HEALTHY
