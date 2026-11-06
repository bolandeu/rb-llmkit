"""Перенос config.toml llmkit < 0.8 в routing v1 (`llm routing import`).

Старый конфиг накладывался на встроенных провайдеров и уровни кода — они
здесь (`LEGACY_DEFAULTS`), чтобы файл с одними настройками переносился без потерь.
Ключи (`api_key`) не переносятся: в routing — только имя переменной `key_env`.
Цены и подписки не переносятся: и то и другое теперь у шлюза.
"""

from __future__ import annotations

import copy
import tomllib
from pathlib import Path
from typing import Any

from .keys import default_env
from .routing import PROTOCOL, SUBSCRIPTION_PROTOCOLS

# Встроенные провайдеры и уровни llmkit 0.7 (config.DEFAULTS тех версий).
LEGACY_DEFAULTS: dict[str, Any] = {
    "providers": {
        "openrouter": {"kind": "openrouter"},
        "ollama": {"kind": "ollama", "base_url": "https://ollama.com"},
        "ccode": {"kind": "openai_compatible", "base_url": "https://all-api.ccode.dev/v1", "mode": "TOOLS"},
        "anymodel": {"kind": "openai_compatible", "base_url": "https://anymodel.org/v1", "mode": "TOOLS"},
        "chatgpt": {"kind": "chatgpt", "requires_key": False},
        "claude": {"kind": "claude_cli", "requires_key": False},
    },
    "levels": {
        "cheap": ["ollama/gpt-oss:120b", "openrouter/openai/gpt-4o-mini"],
        "judge": ["openrouter/anthropic/claude-sonnet-4", "openrouter/openai/gpt-4o"],
        "strong": ["openrouter/anthropic/claude-opus-4"],
        "decide": ["openrouter/~typesafe/jev-latest"],
    },
}


def _merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in over.items():
        if isinstance(result.get(key), dict) and isinstance(value, dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = value
    return result


def _provider(name: str, cfg: dict[str, Any], warnings: list[str]) -> dict[str, Any] | None:
    """Провайдер старого конфига → провайдер routing v1; None — перенести нельзя."""
    protocol = cfg.get("kind")
    if not protocol:
        warnings.append(f"providers.{name}: нет kind — провайдер не перенесён")
        return None
    if protocol in SUBSCRIPTION_PROTOCOLS:
        warnings.append(f"providers.{name}: подписка {protocol} больше не провайдер llmkit — ею владеет шлюз")
        return None
    if protocol != PROTOCOL or not cfg.get("base_url"):
        warnings.append(
            f"providers.{name}: провайдер не перенесён — routing v1 называет только {PROTOCOL} с адресом шлюза"
        )
        return None
    provider: dict[str, Any] = {"protocol": protocol, "base_url": cfg["base_url"], "key_env": default_env(name)}
    if cfg.get("api_key_env") and cfg["api_key_env"] != provider["key_env"]:
        warnings.append(f"providers.{name}: ключ читался из {cfg['api_key_env']}, теперь — {provider['key_env']}")
    if cfg.get("requires_key") is False:
        warnings.append(f"providers.{name}: requires_key=false не переносится — ключ теперь нужен всегда")
    if cfg.get("api_key"):
        warnings.append(f"providers.{name}: api_key из файла не перенесён — положите его в {provider['key_env']}")
    if cfg.get("mode"):
        warnings.append(f"providers.{name}: mode={cfg['mode']} не переносится — режим вызова задаёт шлюз")
    if cfg.get("prices"):
        warnings.append(f"providers.{name}: цены не переносятся — расход считает журнал шлюза")
    return provider


def convert(old: dict[str, Any]) -> dict[str, Any]:
    """Старый конфиг (как прочитан из TOML) → {routing, levels, warnings, dropped}."""
    merged = _merge(copy.deepcopy(LEGACY_DEFAULTS), old)
    warnings: list[str] = []
    providers = {
        name: provider
        for name, cfg in merged.get("providers", {}).items()
        if (provider := _provider(name, cfg, warnings)) is not None
    }
    routing: dict[str, Any] = {"version": 1, "providers": providers}
    dropped = sorted(key for key in old if key not in ("providers", "levels"))
    if dropped:
        warnings.append("не переносятся (в routing их нет): " + ", ".join(f"[{key}]" for key in dropped))
    return {"routing": routing, "levels": dict(merged.get("levels", {})), "warnings": warnings, "dropped": dropped}


def read(path: Path) -> dict[str, Any]:
    with path.open("rb") as handle:
        return tomllib.load(handle)
