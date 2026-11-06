"""`llm video`: генерация, правка, продолжение и состояние задания видео шлюза."""

import typer

from . import surface
from .output import JsonOption, emit, enable_json, group, guard

app = group("video", "Видео шлюза: генерация, правка, продолжение, задание по id — `llm video generate`.")


def _show(ctx: typer.Context, promise) -> None:
    data = surface.payload(surface.run(promise))
    emit(ctx, data, surface.human(data))


@app.command("generate")
def generate(
    ctx: typer.Context,
    prompt: str = typer.Argument(..., help="Что снять."),
    model: str = surface.ModelOption,
    routing: str = surface.RoutingOption,
    json_output: bool = JsonOption,
) -> None:
    """Поставить задание видео по описанию.

    Ответ — id задания, его состояние (`status`), ссылка на файл (`url`), модель
    и цена. Коды выхода: 0 — готово, 2 — нет routing, 3 — нет ключа шлюза,
    5 — шлюз недоступен или ответил ошибкой.

    Example: llm video generate "волна на пляже" -m google/veo-3 --json
    """
    enable_json(ctx, json_output)
    with guard(ctx):
        _show(ctx, surface.client(routing).video_generate(prompt, model))


@app.command("edit")
def edit(
    ctx: typer.Context,
    video: str = typer.Argument(..., help="Ссылка на готовое видео."),
    prompt: str = typer.Option(..., "--prompt", help="Что изменить."),
    model: str = surface.ModelOption,
    routing: str = surface.RoutingOption,
    json_output: bool = JsonOption,
) -> None:
    """Поставить задание правки готового видео.

    Ответ — как у `llm video generate`: id задания, состояние, ссылка, модель
    и цена. Коды выхода: 0 — готово, 2 — нет routing, 3 — нет ключа шлюза,
    5 — шлюз недоступен или ответил ошибкой.

    Example: llm video edit https://video.test/1.mp4 --prompt "закат" -m google/veo-3 --json
    """
    enable_json(ctx, json_output)
    with guard(ctx):
        _show(ctx, surface.client(routing).video_edit(video, prompt, model))


@app.command("extend")
def extend(
    ctx: typer.Context,
    video: str = typer.Argument(..., help="Ссылка на готовое видео."),
    prompt: str = typer.Option(..., "--prompt", help="Что добавить дальше."),
    model: str = surface.ModelOption,
    routing: str = surface.RoutingOption,
    json_output: bool = JsonOption,
) -> None:
    """Поставить задание продолжения готового видео.

    Ответ — как у `llm video generate`: id задания, состояние, ссылка, модель
    и цена. Коды выхода: 0 — готово, 2 — нет routing, 3 — нет ключа шлюза,
    5 — шлюз недоступен или ответил ошибкой.

    Example: llm video extend https://video.test/1.mp4 --prompt "дальше" -m google/veo-3 --json
    """
    enable_json(ctx, json_output)
    with guard(ctx):
        _show(ctx, surface.client(routing).video_extend(video, prompt, model))


@app.command("get")
def get(
    ctx: typer.Context,
    video_id: str = typer.Argument(..., help="Id задания из ответа `llm video generate`."),
    routing: str = surface.RoutingOption,
    json_output: bool = JsonOption,
) -> None:
    """Показать задание видео по id: состояние и ссылка на файл, когда оно готово.

    Коды выхода: 0 — готово, 2 — нет routing, 3 — нет ключа шлюза, 5 — шлюз
    недоступен или ответил ошибкой.

    Example: llm video get video_1 --json
    """
    enable_json(ctx, json_output)
    with guard(ctx):
        _show(ctx, surface.client(routing).video(video_id))
