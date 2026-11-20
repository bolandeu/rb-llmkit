"""`llm image`: генерация картинок шлюза — ссылка или файл, без форматов провайдера."""

import typer

from . import surface
from .output import JsonOption, emit, enable_json, group, guard

app = group("image", "Картинки шлюза: генерация — `llm image generate`.")


@app.command("generate")
def generate(
    ctx: typer.Context,
    prompt: str = typer.Argument(..., help="Что нарисовать."),
    model: str = surface.ModelOption,
    out_path: str | None = surface.OutOption,
    size: str | None = typer.Option(None, "--size", help="Размер картинки как его ждёт шлюз, например 1024x1024."),
    routing: str | None = surface.RoutingOption,
    json_output: bool = JsonOption,
) -> None:
    """Сгенерировать картинку по описанию.

    Ответ — `url` картинки или файл `--out`, если шлюз вернул её байтами; модель
    и цена (`cost`) — из ответа шлюза. Коды выхода: 0 — готово, 2 — нет routing
    или не указан `--out` под байты, 3 — нет ключа шлюза, 5 — шлюз недоступен
    или ответил ошибкой.

    Example: llm image generate "кот в шляпе" -m openai/gpt-image-1 --out cat.png --json
    """
    enable_json(ctx, json_output)
    with guard(ctx):
        fields = {"size": size} if size else {}
        answer = surface.run(surface.client(routing).image(prompt, model, **fields))
        path = surface.written(out_path, answer.blob)
        data = {**surface.payload(answer), "path": path}
        emit(ctx, data, surface.human(data))
