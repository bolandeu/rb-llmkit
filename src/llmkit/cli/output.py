"""Единый вывод CLI: JSON-конверт, коды ошибок, stdout/stderr.

Конверт и коды — по конвенциям cli-builder (`reference/conventions.md`).
stdout — только данные (в режиме `--json` там же лежит и конверт ошибки),
stderr — диагностика: строки `Ошибка:`, предупреждения, логи.

Коды выхода (conventions.md cli-builder): 0 — успех, 1 — непредвиденная
ошибка, 2 — неверные аргументы, 3 — нет авторизации, 5 — ошибка провайдера.
"""

import json
import logging
import sys
from collections.abc import Callable
from contextlib import contextmanager

import typer
from rich.console import Console

from ..errors import AllModelsFailed, ConfigError, KeyMissing, LoginMissing

# Консоли: данные — в stdout, всё остальное — в stderr.
out = Console()
err = Console(stderr=True)

JsonOption = typer.Option(False, "--json", help="Машинный вывод: JSON-конверт в stdout.")


class CliError(Exception):
    """Ошибка с кодом для конверта и кодом выхода."""

    def __init__(self, code: str, message: str, action: str | None = None, exit_code: int = 1) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.action = action
        self.exit_code = exit_code


def bad_arguments(message: str, action: str | None = None) -> CliError:
    return CliError("INVALID_ARGUMENTS", message, action, exit_code=2)


def state(ctx: typer.Context) -> dict:
    if ctx.obj is None:
        ctx.obj = {"json": False, "quiet": False, "verbose": False}
    return ctx.obj


def enable_json(ctx: typer.Context, value: bool) -> None:
    """`--json` принимается и до команды, и после неё."""
    if value:
        state(ctx)["json"] = True


def is_json(ctx: typer.Context) -> bool:
    return bool(state(ctx)["json"])


def is_quiet(ctx: typer.Context) -> bool:
    return bool(state(ctx)["quiet"])


def configure_logging(verbose: bool) -> None:
    """Логи библиотеки — в stderr; `--verbose` опускает порог до DEBUG."""
    logging.basicConfig(
        stream=sys.stderr,
        level=logging.DEBUG if verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )


def emit(ctx: typer.Context, payload: dict, render: Callable[[], None] | None = None) -> None:
    """Успешный результат: конверт в JSON-режиме, человеческий вывод иначе."""
    if is_json(ctx):
        print(json.dumps({"ok": True, **payload}, ensure_ascii=False, indent=2))
    elif render is not None and not is_quiet(ctx):
        render()


def _classify(exc: Exception) -> CliError:
    """Ошибки ядра → коды конверта (см. conventions.md)."""
    if isinstance(exc, LoginMissing):
        return CliError("AUTH_REQUIRED", f"нет входа в подписку для провайдера {exc.provider}", exc.action, 3)
    if isinstance(exc, KeyMissing):
        return CliError(
            "AUTH_REQUIRED",
            f"нет ключа для провайдера {exc.provider}",
            f"выполните `llm keys set {exc.provider}`" + (f" или `export {exc.env_var}=...`" if exc.env_var else ""),
            exit_code=3,
        )
    if isinstance(exc, ConfigError):
        return CliError("INVALID_ARGUMENTS", str(exc), "проверьте конфиг: `llm config show`", exit_code=2)
    if isinstance(exc, AllModelsFailed):
        # Ядро ловит KeyMissing внутри цепочки; если все попытки упали
        # по ключам, это не сбой провайдера, а отсутствующая авторизация.
        if exc.error_type == "auth":
            providers = sorted({attempt.provider for attempt in exc.attempts})
            return CliError(
                "AUTH_REQUIRED",
                "нет ключей для моделей цепочки: " + ", ".join(providers),
                "выполните `llm keys set " + providers[0] + "` или задайте переменную окружения"
                "; для провайдера по подписке — `llm auth login " + providers[0] + "`",
                exit_code=3,
            )
        return CliError(
            "PROVIDER_ERROR",
            str(exc),
            "попробуйте другой уровень: `llm ask ... --level judge`",
            exit_code=5,
        )
    return CliError("UNEXPECTED", f"{type(exc).__name__}: {exc}", "повторите с `--verbose`")


@contextmanager
def guard(ctx: typer.Context):
    """Обёртка тела команды: любая ошибка превращается в конверт и код выхода."""
    try:
        yield
    except typer.Exit:
        raise
    except CliError as exc:
        _report(ctx, exc)
    except Exception as exc:  # сеть, провайдер, чужая ошибка — всё равно конверт
        if state(ctx).get("verbose"):
            err.print_exception()
        _report(ctx, _classify(exc))


def _report(ctx: typer.Context, error: CliError) -> None:
    envelope: dict = {"ok": False, "error": {"code": error.code, "message": error.message}}
    if error.action:
        envelope["error"]["action"] = error.action
    # Данные рядом с ошибкой (отчёт `auth status` при коде 3) — команда кладёт их в `state(ctx)["error_data"]`.
    envelope.update(state(ctx).get("error_data") or {})
    if is_json(ctx):
        print(json.dumps(envelope, ensure_ascii=False, indent=2))
    else:
        err.print(f"[red]Ошибка:[/red] {error.message}")
        if error.action:
            err.print(f"Что делать: {error.action}")
    raise typer.Exit(error.exit_code)


def group(name: str, help_text: str) -> typer.Typer:
    """Группа команд, у которой вызов без подкоманды печатает help и выходит с 0."""
    app = typer.Typer(name=name, help=help_text, no_args_is_help=False, invoke_without_command=True)

    @app.callback()
    def _root(ctx: typer.Context) -> None:
        if ctx.invoked_subcommand is None:
            print(ctx.get_help())
            raise typer.Exit(0)

    return app
