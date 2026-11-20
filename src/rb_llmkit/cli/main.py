"""Корневое приложение CLI `llm`."""

import typer

# Импорт модулей регистрирует их команды на `app`; порядок импорта — порядок в справке.
# isort: off
from . import ask, render, models, cost, describe, doctor  # noqa: F401

# isort: on
from ..version import installed_version
from . import audio as audio_mod
from . import auth as auth_mod
from . import chat as chat_mod
from . import config as config_mod
from . import embeddings as embeddings_mod
from . import image as image_mod
from . import model as model_mod
from . import routing as routing_mod
from . import video as video_mod
from . import web as web_mod
from .app import app
from .output import configure_logging

app.add_typer(image_mod.app, name="image")
app.add_typer(audio_mod.app, name="audio")
app.add_typer(video_mod.app, name="video")
app.add_typer(embeddings_mod.app, name="embeddings")
app.add_typer(web_mod.app, name="web")
app.add_typer(model_mod.app, name="model")
app.add_typer(chat_mod.app, name="chat")
app.add_typer(auth_mod.app, name="auth")
app.add_typer(config_mod.app, name="config")
app.add_typer(routing_mod.app, name="routing")


def _version() -> str:
    return installed_version() or "0.0.0+source"  # запуск из исходников без установки


@app.callback()
def root(
    ctx: typer.Context,
    json_output: bool = typer.Option(False, "--json", help="Машинный вывод: JSON-конверт в stdout."),
    quiet: bool = typer.Option(False, "--quiet", help="Не печатать необязательный человеческий вывод."),
    verbose: bool = typer.Option(False, "--verbose", help="Подробная диагностика в stderr."),
    show_version: bool = typer.Option(False, "--version", help="Показать версию и выйти."),
) -> None:
    """Общие флаги; без команды печатается эта справка (код выхода 0)."""
    ctx.obj = {"json": json_output, "quiet": quiet, "verbose": verbose}
    configure_logging(verbose)
    if show_version:
        print(_version())
        raise typer.Exit(0)
    if ctx.invoked_subcommand is None:
        print(ctx.get_help())
        raise typer.Exit(0)


def main() -> None:
    app()
