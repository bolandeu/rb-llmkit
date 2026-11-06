"""`llm web`: поиск в интернете и загрузка страницы через шлюз."""

import typer

from . import surface
from .output import JsonOption, emit, enable_json, group, guard

app = group("web", "Интернет через шлюз: поиск и загрузка страницы — `llm web search`.")


@app.command("search")
def search(
    ctx: typer.Context,
    query: str = typer.Argument(..., help="Поисковый запрос."),
    model: str = surface.ModelOption,
    routing: str = surface.RoutingOption,
    json_output: bool = JsonOption,
) -> None:
    """Найти в интернете: `results` — ссылка, заголовок и сниппет каждого результата.

    Модель и цена — из ответа шлюза. Коды выхода: 0 — готово, 2 — нет routing,
    3 — нет ключа шлюза, 5 — шлюз недоступен или ответил ошибкой.

    Example: llm web search "llmkit" -m perplexity/sonar --json
    """
    enable_json(ctx, json_output)
    with guard(ctx):
        data = surface.payload(surface.run(surface.client(routing).search(query, model)))
        emit(ctx, data, surface.human(data))


@app.command("fetch")
def fetch(
    ctx: typer.Context,
    url: str = typer.Argument(..., help="Адрес страницы."),
    routing: str = surface.RoutingOption,
    json_output: bool = JsonOption,
) -> None:
    """Загрузить страницу через шлюз: адрес, заголовок и текст.

    Коды выхода: 0 — готово, 2 — нет routing, 3 — нет ключа шлюза, 5 — шлюз
    недоступен или ответил ошибкой.

    Example: llm web fetch https://example.com --json
    """
    enable_json(ctx, json_output)
    with guard(ctx):
        data = surface.payload(surface.run(surface.client(routing).fetch(url)))
        emit(ctx, data, surface.human(data))
