"""Команды `llm auth`: вход в подписки ChatGPT и Claude вместо API-ключей."""

import asyncio
import subprocess

import typer

from .. import config as config_mod
from ..providers import SUBSCRIPTION_KINDS
from ..transports import chatgpt_auth, claude_cli
from .output import CliError, JsonOption, bad_arguments, emit, enable_json, err, group, guard, out

app = group("auth", "Вход в подписки (kind = chatgpt | claude_cli) вместо API-ключей.")


def _subscription_provider(name: str):
    config = config_mod.load()
    cfg = config.providers.get(name)
    if cfg is None or cfg.kind not in SUBSCRIPTION_KINDS:
        known = ", ".join(sorted(p for p, c in config.providers.items() if c.kind in SUBSCRIPTION_KINDS)) or "нет"
        raise bad_arguments(f"{name!r} — не провайдер по подписке; такие провайдеры: {known}")
    return cfg


def _chatgpt_row(name: str) -> dict:
    path = chatgpt_auth.default_path()
    auth = chatgpt_auth.read_auth(path)
    row = {"provider": name, "kind": "chatgpt", "logged_in": auth is not None, "auth_file": str(path)}
    if auth is not None:
        row["plan"] = auth.plan_type
        row["token_expires"] = chatgpt_auth.jwt_exp(auth.access_token) or None
    return row


def _claude_row(name: str) -> dict:
    status = asyncio.run(claude_cli.auth_status())
    row = {"provider": name, "kind": "claude_cli", "logged_in": status["loggedIn"], "installed": status["installed"]}
    for key in ("authMethod", "subscriptionType", "error"):
        if status.get(key):
            row[key] = status[key]
    return row


@app.command("status")
def status(ctx: typer.Context, json_output: bool = JsonOption) -> None:
    """Показать, выполнен ли вход в каждую подписку из конфига.

    Токены не печатаются. Код выхода 0, даже если входа нет.
    """
    enable_json(ctx, json_output)
    with guard(ctx):
        config = config_mod.load()
        rows = [
            _chatgpt_row(name) if cfg.kind == "chatgpt" else _claude_row(name)
            for name, cfg in sorted(config.providers.items())
            if cfg.kind in SUBSCRIPTION_KINDS
        ]

        def render() -> None:
            from rich.table import Table

            table = Table(title="Подписки")
            for column in ("Провайдер", "Вид", "Вход", "Подробности"):
                table.add_column(column)
            for row in rows:
                if row["kind"] == "claude_cli" and not row.get("installed"):
                    detail = "CLI `claude` не найден"
                else:
                    detail = row.get("plan") or row.get("subscriptionType") or row.get("error") or ""
                table.add_row(row["provider"], row["kind"], "да" if row["logged_in"] else "нет", str(detail))
            out.print(table)

        emit(ctx, {"providers": rows}, render)


@app.command("login")
def login(
    ctx: typer.Context,
    provider: str = typer.Argument(..., help="Провайдер по подписке из конфига, например chatgpt или claude."),
    browser: bool = typer.Option(False, "--browser", help="ChatGPT: вход через браузер вместо кода устройства."),
    no_open: bool = typer.Option(False, "--no-open", help="ChatGPT --browser: не открывать браузер самому."),
    json_output: bool = JsonOption,
) -> None:
    """Войти в подписку.

    ChatGPT: по умолчанию вход по коду устройства (ссылка и код, браузер может
    быть на другой машине); `--browser` — через локальный redirect на порт 1455.
    Claude: запускается `claude auth login`. Подсказки идут в stderr.
    Коды выхода: 0 — вход выполнен, 2 — не провайдер по подписке, 3 — вход не удался.
    """
    enable_json(ctx, json_output)
    with guard(ctx):
        cfg = _subscription_provider(provider)
        if cfg.kind == "chatgpt":
            path = chatgpt_auth.default_path()
            try:
                if browser:
                    auth = chatgpt_auth.login_browser(path, echo=err.print, open_browser=not no_open)
                else:
                    auth = chatgpt_auth.login_device(path, echo=err.print)
            except chatgpt_auth.SubscriptionAuthError as exc:
                raise CliError("AUTH_FAILED", str(exc), f"повторите `llm auth login {provider}`", 3) from exc
            emit(
                ctx,
                {"provider": provider, "logged_in": True, "plan": auth.plan_type},
                lambda: out.print(f"Вход в ChatGPT выполнен (план: {auth.plan_type or 'неизвестен'})."),
            )
            return
        command = claude_cli.command()
        if command is None:
            raise CliError(
                "AUTH_FAILED", "Claude Code CLI не найден", "установите Claude Code: https://claude.com/claude-code", 3
            )
        code = subprocess.call([*command, "auth", "login"])  # noqa: S603 — команда из PATH или CLAUDE_COMMAND
        if code != 0:
            raise CliError("AUTH_FAILED", f"`claude auth login` завершился с кодом {code}", None, 3)
        emit(ctx, {"provider": provider, "logged_in": True}, lambda: out.print("Вход в Claude выполнен."))


@app.command("logout")
def logout(
    ctx: typer.Context,
    provider: str = typer.Argument(..., help="Провайдер по подписке из конфига."),
    json_output: bool = JsonOption,
) -> None:
    """Выйти из подписки: ChatGPT — удалить файл токенов, Claude — `claude auth logout`.

    Выход без входа не ошибка. Коды выхода: 0 — готово, 2 — не провайдер по подписке.
    """
    enable_json(ctx, json_output)
    with guard(ctx):
        cfg = _subscription_provider(provider)
        if cfg.kind == "chatgpt":
            removed = chatgpt_auth.delete_auth(chatgpt_auth.default_path())
        else:
            command = claude_cli.command()
            removed = command is not None and subprocess.call([*command, "auth", "logout"]) == 0  # noqa: S603
        emit(ctx, {"provider": provider, "logged_out": removed}, lambda: out.print(f"Выход из {provider} выполнен."))
