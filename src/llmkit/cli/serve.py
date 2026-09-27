"""Команда `llm serve`: заглушка до фазы 4."""

import typer

from .output import CliError, JsonOption, enable_json, guard


def serve(
    ctx: typer.Context,
    port: int = typer.Option(8765, "--port", help="Порт локального прокси."),
    json_output: bool = JsonOption,
) -> None:
    """Запустить локальный HTTP-прокси (фаза 4, ещё не реализовано).

    Код выхода 2 — команда пока не работает.

    Example: llm serve --port 8765
    """
    enable_json(ctx, json_output)
    with guard(ctx):
        raise CliError(
            "NOT_IMPLEMENTED",
            "прокси `llm serve` — фаза 4, ещё не реализовано",
            "пока используйте библиотеку llmkit напрямую",
            exit_code=2,
        )
