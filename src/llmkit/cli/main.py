"""Корневое приложение CLI `llm`."""

from importlib.metadata import PackageNotFoundError, version

import typer

from . import ask as ask_mod
from . import auth as auth_mod
from . import config as config_mod
from . import cost as cost_mod
from . import keys as keys_mod
from . import models as models_mod
from . import serve as serve_mod
from .output import configure_logging

DESCRIPTION = "llmkit: вызовы LLM с цепочками моделей, кэшем и учётом расходов"

app = typer.Typer(
    name="llm",
    help=(
        f"{DESCRIPTION}.\n\n"
        "У всех команд есть `--json` (конверт в stdout), диагностика идёт в stderr.\n"
        "Коды выхода: 0 — успех, 1 — непредвиденная ошибка, 2 — неверные аргументы,\n"
        "3 — нет ключа или входа в подписку, 5 — все модели упали.\n\n"
        "Основные параметры `llm ask` и `llm json`:\n\n"
        "  -m, --model ПРОВАЙДЕР/МОДЕЛЬ   одна модель вместо уровня: ccode/gpt-5.6-sol\n\n"
        "  -l, --level УРОВЕНЬ            цепочка моделей из конфига: cheap, judge…\n\n"
        "  -s, --system ТЕКСТ             системное сообщение\n\n"
        "  --schema ФАЙЛ                  JSON Schema ответа (только llm json)\n\n"
        "  --temperature, --max-tokens, --timeout   перекрыть значения из конфига\n\n"
        "  --tag k=v                      метка для учёта расходов, можно несколько\n\n"
        "  --no-cache, --no-retry         без кэша; без повторов на сбойной модели\n\n"
        "Список провайдеров, уровней и моделей: `llm models`. Все параметры\n"
        "команды: `llm <команда> --help`, например `llm ask --help`.\n\n"
        "Примеры:\n\n"
        '  llm ask "Столица Франции?" --level cheap\n\n'
        '  llm ask "Привет" -m ccode/gpt-5.6-sol\n\n'
        '  llm json "Разбери запрос" --schema schema.json\n\n'
        "  llm models · llm cost --since 7d · llm auth status"
    ),
    no_args_is_help=False,
    invoke_without_command=True,
    add_completion=False,
)
app.command("ask")(ask_mod.ask)
app.command("json")(ask_mod.json_command)
app.command("models")(models_mod.models)
app.command("cost")(cost_mod.cost)
app.command("serve")(serve_mod.serve)
app.add_typer(keys_mod.app, name="keys")
app.add_typer(auth_mod.app, name="auth")
app.add_typer(config_mod.app, name="config")


def _version() -> str:
    try:
        return version("rb-llmkit")
    except PackageNotFoundError:  # запуск из исходников без установки
        return "0.0.0+source"


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
