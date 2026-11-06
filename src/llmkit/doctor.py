"""Отчёт `llm doctor` о готовности к работе (Standard, Health): версия, конфиг, routing и шлюз."""

from __future__ import annotations

import os
from typing import Any

from . import config as config_mod
from .gateway import probe
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


def _routing() -> tuple[dict[str, Any], Any]:
    """Routing до вызова модели: файл, который прочитает `llm ask`."""
    from .cli import runtime

    try:
        spec = runtime.routing_spec(None)
        if spec is None:
            hint = f"нет routing: передайте --routing, задайте LLMKIT_ROUTING_FILE или положите {runtime.default_routing_path()}"
            return _check("routing", False, hint), None
        routing = runtime.load_routing(spec, require_chain=False)
    except Exception as exc:
        return _check("routing", False, f"{type(exc).__name__}: {exc}"), None
    return _check("routing", True, spec if not spec.lstrip().startswith("{") else "inline"), routing


def _gateway(routing: Any, transport: Any) -> dict[str, Any]:
    """Доступность шлюза: без него llmkit не работает, поэтому проверка главная."""
    if routing is None:
        return _check("gateway", False, "routing не загрузился: проверять нечего")
    problems = []
    for cfg in routing.providers.values():
        key = os.environ.get(cfg.key_env or "")
        error = probe(cfg.base_url or "", api_key=key, transport=transport)
        if error:
            problems.append(f"шлюз {cfg.base_url} не отвечает: {error}")
    if problems:
        return _check("gateway", False, "; ".join(problems))
    return _check("gateway", True, ", ".join(cfg.base_url or "" for cfg in routing.providers.values()))


def report(transport: Any = None) -> dict[str, Any]:
    """Отчёт: `healthy` и `checks[]`; `transport` подменяет сеть в тестах."""
    config_check, _ = _config()
    routing_check, routing = _routing()
    checks = [_version(), config_check, routing_check, _gateway(routing, transport)]
    return {"healthy": all(check["ok"] for check in checks), "checks": checks}
