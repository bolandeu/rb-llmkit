"""Команды `llm auth`: вход в подписки ChatGPT и Claude, отчёт о здоровье всех доступов."""

import subprocess

import typer
from rich.markup import escape

from .. import config as config_mod
from .. import health
from ..providers import SUBSCRIPTION_KINDS
from ..transports import chatgpt_auth, claude_cli
from .output import (
    CliError,
    JsonOption,
    bad_arguments,
    emit,
    enable_json,
    err,
    group,
    guard,
    is_json,
    is_quiet,
    out,
    state,
)

app = group("auth", "Вход в подписки (kind = chatgpt | claude_cli) и проверка всех доступов: `llm auth status`.")


def _subscription_provider(name: str):
    config = config_mod.load()
    cfg = config.providers.get(name)
    if cfg is None or cfg.kind not in SUBSCRIPTION_KINDS:
        known = ", ".join(sorted(p for p, c in config.providers.items() if c.kind in SUBSCRIPTION_KINDS)) or "нет"
        raise bad_arguments(f"{name!r} — не провайдер по подписке; такие провайдеры: {known}")
    return cfg


@app.command("status")
def status(
    ctx: typer.Context,
    check: bool = typer.Option(
        False, "--check", help="Сделать по одному дешёвому read-only вызову на провайдера (лимит 10 с)."
    ),
    provider: str = typer.Option(None, "--provider", help="Только этот провайдер из конфига (по умолчанию все)."),
    json_output: bool = JsonOption,
) -> None:
    """Показать доступ каждого провайдера: откуда берётся и работает ли. Значения не печатаются.

    Ключи API и подписки (chatgpt, claude_cli) — в одном отчёте. Без `--check`
    только наличие (`unchecked` / `missing`); с ним: openrouter, openai,
    anthropic, gemini, ollama и OpenAI-совместимые шлюзы — один бесплатный
    запрос с ключом; chatgpt — свежесть токена (с обновлением, если истёк);
    claude — локальный `claude auth status`. Модели не вызываются.
    Обязательных провайдеров у llmkit нет (`required: false`).
    Коды выхода: 0 — нет неверных и просроченных доступов, 3 — есть
    (`error.code: CREDENTIALS_UNHEALTHY`, отчёт всё равно выводится),
    2 — неизвестный `--provider`. Форма `--json` — общий контракт инструментов:
    `tool`, `version`, `checked_at`, `credentials[]` с `provider`, `required`,
    `fields`, `source`, `source_ref`, `status`, `expires_at`, `quota`, `message`.

    Example: llm auth status --check --json
    """
    enable_json(ctx, json_output)
    with guard(ctx):
        config = config_mod.load()
        known = sorted(name for name, cfg in config.providers.items() if health.has_credentials(cfg))
        if provider is not None and provider not in known:
            raise bad_arguments(f"провайдер {provider!r} не найден среди провайдеров с доступом: {', '.join(known)}")
        report = health.report(config, check=check, only=provider)
        problems = [
            f"{item['provider']}: {item['status']}" for item in report["credentials"] if health.is_problem(item)
        ]
        if not problems:
            emit(ctx, report, lambda: _render_status(report))
            return
        if not is_json(ctx) and not is_quiet(ctx):
            _render_status(report)
        state(ctx)["error_data"] = report  # отчёт — данные и при коде 3
        raise CliError(
            "CREDENTIALS_UNHEALTHY",
            "проблемы с доступом: " + ", ".join(problems),
            "обновите ключ `llm keys set <провайдер>` или войдите заново `llm auth login <провайдер>`",
            exit_code=3,
        )


def _render_status(report: dict) -> None:
    if not report["credentials"]:
        out.print("Провайдеров с доступом нет.")
    for item in report["credentials"]:
        mark = {"ok": "[green]✓[/green]", "unchecked": "[dim]·[/dim]"}.get(item["status"], "[red]✗[/red]")
        detail = f" — {item['message']}" if item["message"] else ""
        quota = item["quota"]
        left = f", остаток {quota['remaining']} {quota['unit']}" if quota and quota.get("remaining") is not None else ""
        line = f"{item['provider']}: {item['status']} ({item['source']}: {item['source_ref']}){left}{detail}"
        out.print(f"{mark} {escape(line)}")


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

    Example: llm auth login chatgpt
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

    Example: llm auth logout chatgpt
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
