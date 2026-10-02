"""Команды `llm config`: пути файлов и итоговые настройки вызовов.

С 0.8.0 файла конфига нет: провайдеры и цепочка — routing v1 (`llm routing`).
"""

import os

import typer

from .. import config as config_mod
from . import runtime
from .output import JsonOption, emit, enable_json, group, guard, out

app = group("config", "Настройки llmkit: где лежат кэш, журнал и файл routing, что получилось в итоге.")


@app.command("path")
def path(ctx: typer.Context, json_output: bool = JsonOption) -> None:
    """Показать пути кэша, журнала вызовов и файла routing (LLMKIT_ROUTING_FILE).

    Код выхода всегда 0.

    Example: llm config path
    """
    enable_json(ctx, json_output)
    with guard(ctx):
        config = config_mod.load()
        payload = {
            "routing_file": os.environ.get(runtime.ROUTING_FILE_ENV),
            "cache": str(config.cache_path()),
            "usage": str(config.usage_path()),
        }

        def render() -> None:
            for name, value in payload.items():
                out.print(f"{name}: {value or '—'}")

        emit(ctx, payload, render)


@app.command("show")
def show(ctx: typer.Context, json_output: bool = JsonOption) -> None:
    """Показать итоговые настройки вызовов: дефолты кода и LLMKIT_*.

    Провайдеров и цепочек здесь нет — они в routing (`llm models`).
    Коды выхода: 0 — готово, 2 — настройки не проходят проверку.

    Example: llm config show --json
    """
    enable_json(ctx, json_output)
    with guard(ctx):
        data = config_mod.load().model_dump(mode="json")

        def render() -> None:
            import json

            out.print(json.dumps(data, ensure_ascii=False, indent=2), highlight=False, markup=False)

        emit(ctx, {"config": data}, render)
