"""`llm embeddings`: векторы текста из шлюза."""

import typer

from . import surface
from .output import JsonOption, emit, enable_json, group, guard

app = group("embeddings", "Векторы текста шлюза — `llm embeddings create`.")


@app.command("create")
def create(
    ctx: typer.Context,
    text: str = typer.Argument(..., help="Текст, для которого нужны векторы."),
    model: str = surface.ModelOption,
    routing: str = surface.RoutingOption,
    json_output: bool = JsonOption,
) -> None:
    """Получить векторы текста: `embeddings` по порядку, модель и цена из ответа шлюза.

    Коды выхода: 0 — готово, 2 — нет routing, 3 — нет ключа шлюза, 5 — шлюз
    недоступен или ответил ошибкой.

    Example: llm embeddings create "текст" -m openai/text-embedding-3-small --json
    """
    enable_json(ctx, json_output)
    with guard(ctx):
        data = surface.payload(surface.run(surface.client(routing).embeddings(text, model)))
        emit(ctx, data, surface.human(data))
