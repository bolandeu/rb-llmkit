"""Корневое приложение CLI `llm`."""

import typer

# Импорт модулей регистрирует их команды на `app`; порядок импорта — порядок в справке.
# isort: off
from . import ask, models, cost, serve  # noqa: F401

# isort: on
from ..version import installed_version
from . import auth as auth_mod
from . import config as config_mod
from . import keys as keys_mod
from .app import app
from .output import configure_logging

app.add_typer(keys_mod.app, name="keys")
app.add_typer(auth_mod.app, name="auth")
app.add_typer(config_mod.app, name="config")


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
