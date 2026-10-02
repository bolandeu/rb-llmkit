"""Команда `llm describe`: контракт CLI документом OpenCLI."""

import json

import typer

from .app import app
from .output import enable_json, guard, is_json


@app.command("describe")
def describe(
    ctx: typer.Context,
    json_output: bool = typer.Option(False, "--json", help='Документ одной строкой, без конверта {"ok": ...}.'),
) -> None:
    """Показать машиночитаемый контракт CLI: документ OpenCLI (opencli.org).

    Команды, опции, аргументы, коды выхода и метаданные `x-rb-*`: env, таблицы,
    представления v1, файлы данных и кэша, внешние программы. С --json — сам
    документ одной строкой (без конверта {"ok": ...}), без него — тот же с отступами.

    Example: llm describe --json
    """
    enable_json(ctx, json_output)
    with guard(ctx):
        from .. import opencli

        document = opencli.document(ctx.find_root().command)
        print(json.dumps(document, ensure_ascii=False, indent=None if is_json(ctx) else 2))
