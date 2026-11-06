"""`llm model`: модели шлюза — список, подробности, одна модель.

Группа называется `model`: `llm models` — провайдеры routing, это другая команда.
"""

import typer

from . import surface
from .output import JsonOption, emit, enable_json, group, guard

app = group("model", "Модели шлюза: список, подробности, одна модель — `llm model list`.")


def _show(ctx: typer.Context, payload: dict) -> None:
    emit(ctx, payload, surface.human(payload))


@app.command("list")
def model_list(
    ctx: typer.Context,
    routing: str = surface.RoutingOption,
    json_output: bool = JsonOption,
) -> None:
    """Список моделей шлюза формой OpenAI: `models` как их отдал шлюз.

    Коды выхода: 0 — готово, 2 — нет routing, 3 — нет ключа шлюза, 5 — шлюз
    недоступен или ответил ошибкой.

    Example: llm model list --json
    """
    enable_json(ctx, json_output)
    with guard(ctx):
        _show(ctx, {"models": surface.run(surface.client(routing).model_list())})


@app.command("info")
def model_info(
    ctx: typer.Context,
    routing: str = surface.RoutingOption,
    json_output: bool = JsonOption,
) -> None:
    """Модели шлюза с подробностями: провайдер и вид услуги каждой.

    Коды выхода: 0 — готово, 2 — нет routing, 3 — нет ключа шлюза, 5 — шлюз
    недоступен или ответил ошибкой.

    Example: llm model info --json
    """
    enable_json(ctx, json_output)
    with guard(ctx):
        _show(ctx, {"models": surface.run(surface.client(routing).model_info())})


@app.command("show")
def model_show(
    ctx: typer.Context,
    model_id: str = typer.Argument(..., help="Id модели как его отдаёт `llm model list`."),
    routing: str = surface.RoutingOption,
    json_output: bool = JsonOption,
) -> None:
    """Показать одну модель шлюза по id.

    Коды выхода: 0 — готово, 2 — нет routing, 3 — нет ключа шлюза, 5 — шлюз
    недоступен, ответил ошибкой или не знает такую модель.

    Example: llm model show deepseek/deepseek-v4.1-flash-1017 --json
    """
    enable_json(ctx, json_output)
    with guard(ctx):
        _show(ctx, {"model": surface.run(surface.client(routing).model(model_id))})
