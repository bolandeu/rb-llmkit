"""`llm audio`: речь шлюза — озвучка, расшифровка и голоса."""

from pathlib import Path

import typer

from . import surface
from .output import JsonOption, bad_arguments, emit, enable_json, group, guard

app = group("audio", "Речь шлюза: озвучка, расшифровка, голоса — `llm audio speech` и другие.")


@app.command("speech")
def speech(
    ctx: typer.Context,
    text: str = typer.Argument(..., help="Что озвучить."),
    model: str = surface.ModelOption,
    out_path: str = typer.Option(..., "--out", help="Файл для байтов речи: шлюз отвечает не JSON."),
    voice: str = typer.Option(None, "--voice", help="Голос шлюза; список — `llm audio voices`."),
    fmt: str = typer.Option(None, "--format", help="Формат ответа как его ждёт шлюз, например mp3."),
    routing: str = surface.RoutingOption,
    json_output: bool = JsonOption,
) -> None:
    """Озвучить текст: шлюз отдаёт байты речи, команда пишет их в `--out`.

    Ответ — путь к файлу и его content-type. Коды выхода: 0 — готово, 2 — нет
    routing, 3 — нет ключа шлюза, 5 — шлюз недоступен или ответил ошибкой.

    Example: llm audio speech "привет" -m openai/gpt-4o-mini-tts --voice alloy --out speech.mp3 --json
    """
    enable_json(ctx, json_output)
    with guard(ctx):
        answer = surface.run(surface.client(routing).speech(text, model, voice=voice, fmt=fmt))
        data = {
            "path": surface.written(out_path, answer.blob),
            "content_type": answer.content_type,
            "model": answer.model,
        }
        emit(ctx, data, surface.human(data))


@app.command("transcribe")
def transcribe(
    ctx: typer.Context,
    file: str = typer.Argument(..., help="Файл с речью."),
    model: str = surface.ModelOption,
    language: str = typer.Option(None, "--language", help="Язык речи кодом, например ru."),
    routing: str = surface.RoutingOption,
    json_output: bool = JsonOption,
) -> None:
    """Расшифровать речь из файла: текст, модель и цена из ответа шлюза.

    Коды выхода: 0 — готово, 2 — нет routing или файла, 3 — нет ключа шлюза,
    5 — шлюз недоступен или ответил ошибкой.

    Example: llm audio transcribe speech.mp3 -m openai/whisper-1 --json
    """
    enable_json(ctx, json_output)
    with guard(ctx):
        if not Path(file).is_file():
            raise bad_arguments(f"нет файла {file}", "передайте путь к файлу с речью")
        data = surface.payload(surface.run(surface.client(routing).transcribe(file, model, language=language)))
        emit(ctx, data, surface.human(data))


@app.command("voices")
def voices(
    ctx: typer.Context,
    routing: str = surface.RoutingOption,
    json_output: bool = JsonOption,
) -> None:
    """Список голосов шлюза для `llm audio speech --voice`.

    Коды выхода: 0 — готово, 2 — нет routing, 3 — нет ключа шлюза, 5 — шлюз
    недоступен или ответил ошибкой.

    Example: llm audio voices --json
    """
    enable_json(ctx, json_output)
    with guard(ctx):
        data = {"voices": surface.run(surface.client(routing).voices())}
        emit(ctx, data, surface.human(data))
