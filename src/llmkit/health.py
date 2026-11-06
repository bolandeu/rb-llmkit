"""Здоровье доступа к шлюзу: отчёт `llm auth status [--check]` (tools/docs/standard-release.md §8).

Форма отчёта — общий контракт инструментов (`tools-watch` читает её, не зная
провайдеров), её фиксирует `tests/test_health.py`; изменение формы — ломающее
изменение. Подписок в отчёте нет: они живут в шлюзе, а у llmkit один доступ —
ключ шлюза из переменной окружения (`key_env` провайдера routing).

Без `check` отчёт только про наличие ключа (`unchecked` / `missing`).
С `check` — один дешёвый вызов `/models` шлюза, жёсткий лимит 10 с, без повторов.
Значение ключа наружу не выходит: им только вычищаются сообщения.
"""

from __future__ import annotations

import concurrent.futures
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from . import keys
from .routing import Provider, Routing
from .version import installed_version

TOOL = "llmkit"
CHECK_TIMEOUT = 10.0
# Проблема даже у необязательного провайдера: ключ есть, но неверный.
ALWAYS_PROBLEMS = frozenset({"invalid", "expired"})
HEALTHY = frozenset({"ok", "unchecked"})


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


def check_key(kind: str, api_key: str, base_url: str | None, *, transport: Any = None) -> Health:
    """Один дешёвый GET `/models` шлюза с ключом: 401/403 — invalid, 429/5xx/сеть — unreachable.

    `kind` — протокол провайдера: routing v1 называет только `openai_compatible`,
    так что проверка одна — список моделей OpenAI-совместимого шлюза.
    """
    import httpx

    url = f"{(base_url or '').rstrip('/')}/models"
    try:
        with httpx.Client(timeout=CHECK_TIMEOUT, transport=transport) as client:
            response = client.get(url, headers={"Authorization": f"Bearer {api_key}"})
    except httpx.HTTPError as exc:
        return Health("unreachable", message=f"{type(exc).__name__}: {exc}")
    if response.status_code in (401, 403):
        return Health("invalid", message=f"шлюз отверг ключ (HTTP {response.status_code})")
    if response.status_code == 429:
        return Health("unreachable", message="лимит запросов (HTTP 429), повторите позже")
    if response.status_code >= 400:
        return Health("unreachable", message=f"HTTP {response.status_code}")
    return Health()


def _blank(name: str, fields: list[str], source_ref: str) -> dict[str, Any]:
    return {
        "provider": name,
        # llmkit работает с любым подмножеством провайдеров routing — обязательных нет.
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


def _key_entry(name: str, cfg: Provider, check: bool, env: Mapping[str, str]) -> dict[str, Any]:
    """Строка отчёта по ключу шлюза: только переменная окружения, другого источника нет."""
    env_name = keys.env_var(name, cfg)
    entry = _blank(name, ["api_key"], env_name)
    value = env.get(env_name)
    if not value:
        entry["message"] = f"`export {env_name}=...` — ключ шлюза берётся только из окружения"
        return entry
    entry.update(source="env", source_ref=env_name)
    if not check:
        entry["status"] = "unchecked"
        return entry
    return _apply(entry, _with_timeout(lambda: check_key(cfg.protocol, value, cfg.base_url)), [value])


def providers_of(routing: Routing | None) -> dict[str, Provider]:
    """Провайдеры отчёта — только из routing: своих доступов у llmkit нет."""
    return dict(routing.providers) if routing is not None else {}


def credential_entry(name: str, cfg: Provider, *, check: bool, env: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Строка отчёта §8 для одного провайдера."""
    return _key_entry(name, cfg, check, os.environ if env is None else env)


def report(routing: Routing | None, *, check: bool, only: str | None = None) -> dict[str, Any]:
    """Отчёт §8 по провайдерам routing (или по одному, `only`)."""
    return {
        "tool": TOOL,
        "version": _version(),
        "checked_at": _iso(_now()),
        "credentials": [
            credential_entry(name, cfg, check=check)
            for name, cfg in sorted(providers_of(routing).items())
            if only is None or name == only
        ],
    }


def is_problem(item: dict[str, Any]) -> bool:
    """Код выхода 3: неверный/просроченный ключ у любого, иная беда — у обязательного."""
    if item["status"] in ALWAYS_PROBLEMS:
        return True
    return bool(item["required"]) and item["status"] not in HEALTHY
