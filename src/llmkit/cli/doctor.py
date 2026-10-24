"""Команда `llm doctor`: отчёт о готовности llm к работе."""

import typer

from .. import doctor as doctor_mod
from .app import app
from .output import JsonOption, emit, enable_json, guard, out


@app.command("doctor")
def doctor(
    ctx: typer.Context,
    json_output: bool = JsonOption,
) -> None:
    """Проверить, готов ли llm к работе: версия, конфиг, routing, база расходов, внешние программы.

    Проверки локальные, без сети и без вызовов моделей (доступы провайдеров — `llm auth status`).
    Отчёт — результат команды: код выхода 0, даже если `healthy` ложно.
    Форма `--json`: `healthy` и `checks[]` с `name`, `ok`, `detail`.

    Example: llm doctor --json
    """
    enable_json(ctx, json_output)
    with guard(ctx):
        result = doctor_mod.report()

        def render() -> None:
            for check in result["checks"]:
                mark = "[green]✓[/green]" if check["ok"] else "[red]✗[/red]"
                out.print(f"{mark} {check['name']}" + (f" — {check['detail']}" if check.get("detail") else ""))

        emit(ctx, result, render)
