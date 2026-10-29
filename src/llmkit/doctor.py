"""Отчёт `llm doctor` о готовности к работе (Standard, Health): локальные проверки, без сети и без вызовов моделей."""

from __future__ import annotations

import shutil
from typing import Any

from . import config as config_mod
from . import opencli
from .version import installed_version


def _check(name: str, ok: bool, detail: str | None = None) -> dict[str, Any]:
    return {"name": name, "ok": ok, **({"detail": detail} if detail else {})}


def _version() -> dict[str, Any]:
    version = installed_version()
    return _check("version", version is not None, version or "пакет не установлен (запуск из исходников)")


def _config() -> tuple[dict[str, Any], config_mod.Config | None]:
    try:
        loaded = config_mod.load()
    except Exception as exc:
        return _check("config", False, f"{type(exc).__name__}: {exc}"), None
    return _check("config", True), loaded


def _routing() -> dict[str, Any]:
    from .cli import runtime

    try:
        spec = runtime.routing_spec(None)
        if spec is None:
            hint = f"нет routing: передайте --routing, задайте LLMKIT_ROUTING_FILE или положите {runtime.default_routing_path()}"
            return _check("routing", False, hint)
        runtime.load_routing(spec, require_chain=False)
    except Exception as exc:
        return _check("routing", False, f"{type(exc).__name__}: {exc}")
    return _check("routing", True, spec if not spec.lstrip().startswith("{") else "inline")


def _database(name: str, loaded: config_mod.Config | None) -> dict[str, Any]:
    """База журнала и кэша: открывается, схема на месте; при ошибке — её текст, не путь файла."""
    from . import db

    if loaded is None:
        return _check(name, False, "конфиг не загрузился")
    try:
        engine = db.open_db(loaded.usage_path())
    except Exception as exc:
        return _check(name, False, f"{type(exc).__name__}: {exc}")
    try:
        return _check(name, True, db.describe(engine))
    finally:
        engine.dispose()


def _external() -> list[dict[str, Any]]:
    """Внешние программы из `[[tool.rb.external]]`; `claude` ищется так же, как его запускает транспорт."""
    from .transports import claude_cli

    checks = []
    for program in opencli.external():
        name = program["name"]
        present = claude_cli.command() is not None if name == "claude" else shutil.which(name) is not None
        required = program["required"]
        detail = "найден" if present else ("не найден" if required else "не найден (необязателен)")
        checks.append(_check(f"external:{name}", present or not required, detail))
    return checks


def report() -> dict[str, Any]:
    config_check, loaded = _config()
    checks = [
        _version(),
        config_check,
        _routing(),
        _database("usage-db", loaded),
        _database("cache", loaded),
        *_external(),
    ]
    return {"healthy": all(check["ok"] for check in checks), "checks": checks}
