"""Единый вывод CLI: JSON-конверт, коды ошибок, stdout/stderr.

Конверт и коды — по конвенциям cli-builder (`reference/conventions.md`).
stdout — только данные (в режиме `--json` там же лежит и конверт ошибки),
stderr — диагностика: строки `Ошибка:`, предупреждения, логи.

Коды выхода (conventions.md cli-builder): 0 — успех, 1 — непредвиденная
ошибка (и база не смигрирована), 2 — неверные аргументы, 3 — нет авторизации,
5 — ошибка провайдера или база недоступна, 6 — базу смигрировал более новый релиз.
"""

import json
import logging
import sys
from collections.abc import Callable
from contextlib import contextmanager

import typer
from rich.console import Console

from ..errors import (
    AllModelsFailed,
    ConfigError,
    DatabaseError,
    KeyMissing,
    LoginMissing,
    RoutingInvalid,
    RoutingMissing,
    TemplateError,
    TemplateVariableMissing,
)

# Консоли: данные — в stdout, всё остальное — в stderr.
out = Console()
err = Console(stderr=True)

JsonOption = typer.Option(False, "--json", help="Машинный вывод: JSON-конверт в stdout.")


class CliError(Exception):
    """Ошибка с кодом для конверта и кодом выхода."""

    def __init__(
        self, code: str, message: str, action: str | None = None, exit_code: int = 1, details: dict | None = None
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.action = action
        self.exit_code = exit_code
        self.details = details or {}  # дополнительные поля объекта error в конверте


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
    if isinstance(exc, DatabaseError):
        return CliError(exc.code, exc.message, exc.action, exc.exit_code)
    if isinstance(exc, LoginMissing):
        return CliError("AUTH_REQUIRED", f"нет входа в подписку для провайдера {exc.provider}", exc.action, exit_code=3)
    if isinstance(exc, KeyMissing):
        return CliError(
            "AUTH_MISSING",
            f"нет ключа для провайдера {exc.provider}: переменная {exc.env_var}",
            f"`export {exc.env_var}=...` или `llm keys set {exc.provider}`",
            exit_code=3,
            details={"variable": exc.env_var},
        )
    if isinstance(exc, RoutingMissing):
        from .runtime import default_routing_path  # runtime импортирует output

        return CliError(
            "ROUTING_MISSING",
            str(exc),
            "передайте --routing '<json>' или путь к JSON-файлу, задайте LLMKIT_ROUTING_FILE "
            f"или положите файл по умолчанию {default_routing_path()}; "
            "старый config.toml не читается — перенести: `llm routing import <config.toml>`",
            exit_code=2,
        )
    if isinstance(exc, RoutingInvalid):
        return CliError(
            "ROUTING_INVALID",
            str(exc),
            "проверьте routing: `llm routing validate <файл|json>`",
            exit_code=2,
            details={"path": exc.path},
        )
    if isinstance(exc, TemplateVariableMissing):
        return CliError(
            "TEMPLATE_VARIABLE_MISSING",
            str(exc),
            f"добавьте {exc.name!r} в --vars или повторите с --lenient",
            exit_code=2,
            details={"variable": exc.name},
        )
    if isinstance(exc, TemplateError):
        return CliError("INVALID_ARGUMENTS", str(exc), "проверьте шаблон", exit_code=2)
    if isinstance(exc, ConfigError):
        return CliError("INVALID_ARGUMENTS", str(exc), "проверьте конфиг: `llm config show`", exit_code=2)
    if isinstance(exc, AllModelsFailed):
        attempts = [{"model": a.model, "error_code": a.error_type} for a in exc.attempts]
        # Ядро ловит KeyMissing внутри цепочки; если все попытки упали
        # по ключам, это не сбой провайдера, а отсутствующая авторизация.
        if exc.error_type == "auth" and exc.missing_keys:
            return CliError(
                "AUTH_MISSING",
                "нет ключей для моделей цепочки: " + ", ".join(exc.missing_keys),
                f"`export {exc.missing_keys[0]}=...` или `llm keys set <провайдер>`",
                exit_code=3,
                details={"variable": exc.missing_keys[0], "variables": exc.missing_keys, "attempts": attempts},
            )
        if exc.error_type == "auth":
            providers = sorted({attempt.provider for attempt in exc.attempts})
            return CliError(
                "AUTH_REQUIRED",
                "нет ключей для моделей цепочки: " + ", ".join(providers),
                "выполните `llm keys set " + providers[0] + "` или задайте переменную окружения"
                "; для провайдера по подписке — `llm auth login " + providers[0] + "`",
                exit_code=3,
                details={"attempts": attempts},
            )
        spent = exc.answer
        return CliError(
            "PROVIDER_ERROR",
            str(exc),
            "попробуйте другую цепочку: -m провайдер/модель … или routing.chain",
            exit_code=5,
            details={
                "attempts": attempts,
                # Упавшая цепочка тоже стоит денег: неразобранные ответы провайдер списал.
                "billable_requests": spent.billable_requests if spent else 0,
                "cost_total": spent.cost_total if spent else 0.0,
                "cost_currency": "USD",
            },
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
    envelope["error"].update(error.details)
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
