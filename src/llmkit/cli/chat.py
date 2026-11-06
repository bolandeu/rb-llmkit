"""`llm chat`: прочие формы чата шлюза — responses, messages, systemone, api, модели Gemini."""

import typer

from . import surface
from .output import JsonOption, emit, enable_json, group, guard

app = group("chat", "Прочие формы чата шлюза: responses, messages, systemone, api, модели Gemini.")


def _show(ctx: typer.Context, promise) -> None:
    """Ответ формы чата в конверт и в человеческий вывод."""
    data = surface.answer_payload(surface.run(promise))
    emit(ctx, data, surface.human(data))


@app.command("responses")
def responses(
    ctx: typer.Context,
    prompt: str = typer.Argument(..., help="Текст запроса."),
    model: str = surface.ModelOption,
    routing: str = surface.RoutingOption,
    json_output: bool = JsonOption,
) -> None:
    """Спросить шлюз формой `responses`: текст `output`, модель и цена.

    Коды выхода: 0 — готово, 2 — нет routing, 3 — нет ключа шлюза, 5 — шлюз
    недоступен или ответил ошибкой.

    Example: llm chat responses "Столица Франции?" -m openai/gpt-5 --json
    """
    enable_json(ctx, json_output)
    with guard(ctx):
        _show(ctx, surface.client(routing).responses(prompt, model))


@app.command("responses-compact")
def responses_compact(
    ctx: typer.Context,
    prompt: str = typer.Argument(..., help="Текст запроса."),
    model: str = surface.ModelOption,
    routing: str = surface.RoutingOption,
    json_output: bool = JsonOption,
) -> None:
    """Спросить шлюз формой `responses` со сжатием: текст, модель и цена.

    Коды выхода: 0 — готово, 2 — нет routing, 3 — нет ключа шлюза, 5 — шлюз
    недоступен или ответил ошибкой.

    Example: llm chat responses-compact "Столица Франции?" -m openai/gpt-5 --json
    """
    enable_json(ctx, json_output)
    with guard(ctx):
        _show(ctx, surface.client(routing).responses(prompt, model, compact=True))


@app.command("messages")
def messages(
    ctx: typer.Context,
    prompt: str = typer.Argument(..., help="Текст запроса."),
    model: str = surface.ModelOption,
    routing: str = surface.RoutingOption,
    json_output: bool = JsonOption,
) -> None:
    """Спросить шлюз формой `messages` (Anthropic): текст блоков `content`, модель и цена.

    Коды выхода: 0 — готово, 2 — нет routing, 3 — нет ключа шлюза, 5 — шлюз
    недоступен или ответил ошибкой.

    Example: llm chat messages "Столица Франции?" -m anthropic/claude-x --json
    """
    enable_json(ctx, json_output)
    with guard(ctx):
        _show(ctx, surface.client(routing).messages(prompt, model))


@app.command("count-tokens")
def count_tokens(
    ctx: typer.Context,
    prompt: str = typer.Argument(..., help="Текст запроса."),
    model: str = surface.ModelOption,
    routing: str = surface.RoutingOption,
    json_output: bool = JsonOption,
) -> None:
    """Сколько токенов шлюз насчитал запросу: поле `tokens`.

    Модель не вызывается. Коды выхода: 0 — готово, 2 — нет routing, 3 — нет
    ключа шлюза, 5 — шлюз недоступен или ответил ошибкой.

    Example: llm chat count-tokens "Столица Франции?" -m openai/gpt-5 --json
    """
    enable_json(ctx, json_output)
    with guard(ctx):
        data = {"tokens": surface.run(surface.client(routing).count_tokens(prompt, model))}
        emit(ctx, data, surface.human(data))


@app.command("systemone")
def systemone(
    ctx: typer.Context,
    prompt: str = typer.Argument(..., help="Текст запроса."),
    model: str = surface.ModelOption,
    routing: str = surface.RoutingOption,
    json_output: bool = JsonOption,
) -> None:
    """Спросить шлюз формой `systemone`: текст, провайдер и цена.

    Коды выхода: 0 — готово, 2 — нет routing, 3 — нет ключа шлюза, 5 — шлюз
    недоступен или ответил ошибкой.

    Example: llm chat systemone "вопрос" -m openai/gpt-5 --json
    """
    enable_json(ctx, json_output)
    with guard(ctx):
        _show(ctx, surface.client(routing).systemone(prompt, model))


@app.command("api")
def api(
    ctx: typer.Context,
    prompt: str = typer.Argument(..., help="Текст запроса."),
    model: str = surface.ModelOption,
    routing: str = surface.RoutingOption,
    json_output: bool = JsonOption,
) -> None:
    """Спросить шлюз формой `/api/chat`: текст, провайдер и цена.

    Коды выхода: 0 — готово, 2 — нет routing, 3 — нет ключа шлюза, 5 — шлюз
    недоступен или ответил ошибкой.

    Example: llm chat api "вопрос" -m openai/gpt-5 --json
    """
    enable_json(ctx, json_output)
    with guard(ctx):
        _show(ctx, surface.client(routing).api_chat(prompt, model))


@app.command("gemini-models")
def gemini_models(
    ctx: typer.Context,
    routing: str = surface.RoutingOption,
    json_output: bool = JsonOption,
) -> None:
    """Модели шлюза в форме Gemini (`name`, `displayName`) с `/v1beta/models`.

    Коды выхода: 0 — готово, 2 — нет routing, 3 — нет ключа шлюза, 5 — шлюз
    недоступен или ответил ошибкой.

    Example: llm chat gemini-models --json
    """
    enable_json(ctx, json_output)
    with guard(ctx):
        data = {"models": surface.run(surface.client(routing).gemini_models())}
        emit(ctx, data, surface.human(data))
