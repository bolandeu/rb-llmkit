"""Команда `llm config show`: итоговые настройки вызова.

Файла конфига нет: провайдеры и цепочка — routing v1 (`llm routing`), своего
состояния у llmkit тоже нет — только дефолты вызова, env и аргументы `LlmKit(...)`.
"""

import typer

from .. import config as config_mod
from .output import JsonOption, emit, enable_json, group, guard, out

app = group("config", "Настройки вызова: дефолты кода и LLMKIT_* — что получилось в итоге.")


@app.command("show")
def show(ctx: typer.Context, json_output: bool = JsonOption) -> None:
    """Показать итоговые настройки вызова: дефолты кода и переменные LLMKIT_*.

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
