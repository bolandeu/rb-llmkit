"""Команды `llm config`: пути файлов и итоговые настройки вызовов.

С 0.8.0 файла конфига нет: провайдеры и цепочка — routing v1 (`llm routing`).
"""

import os

import typer

from .. import config as config_mod
from .. import db
from . import runtime
from .output import JsonOption, emit, enable_json, group, guard, out

app = group("config", "Настройки llmkit: где лежат кэш и журнал (база), файл routing, что получилось в итоге.")


@app.command("path")
def path(ctx: typer.Context, json_output: bool = JsonOption) -> None:
    """Показать, где лежат кэш и журнал вызовов (база) и файл routing (LLMKIT_ROUTING_FILE или файл по умолчанию).

    Код выхода всегда 0.

    Example: llm config path
    """
    enable_json(ctx, json_output)
    with guard(ctx):
        config = config_mod.load()
        payload = {
            "routing_file": os.environ.get(runtime.ROUTING_FILE_ENV)
            or (str(default) if (default := runtime.default_routing_path()).is_file() else None),
            "routing_default": str(runtime.default_routing_path()),
            "cache": db.location(config.usage_path()),  # кэш лежит в базе журнала
            "usage": str(config.usage_path()),
        }

        def render() -> None:
            for name, value in payload.items():
                out.print(f"{name}: {value or '—'}")

        emit(ctx, payload, render)


@app.command("show")
def show(ctx: typer.Context, json_output: bool = JsonOption) -> None:
    """Показать итоговые настройки вызовов: дефолты кода и LLMKIT_*, где лежит кэш.

    Провайдеров и цепочек здесь нет — они в routing (`llm models`).
    Коды выхода: 0 — готово, 2 — настройки не проходят проверку.

    Example: llm config show --json
    """
    enable_json(ctx, json_output)
    with guard(ctx):
        loaded = config_mod.load()
        data = loaded.model_dump(mode="json")

        def render() -> None:
            import json

            out.print(json.dumps(data, ensure_ascii=False, indent=2), highlight=False, markup=False)

        emit(ctx, {"config": data, "cache": db.location(loaded.usage_path())}, render)
