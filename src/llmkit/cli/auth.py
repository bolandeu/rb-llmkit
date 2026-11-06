"""Команда `llm auth`: здоровье доступа к шлюзу — `llm auth status`."""

import typer
from rich.markup import escape

from .. import health
from . import runtime
from .output import (
    CliError,
    JsonOption,
    bad_arguments,
    emit,
    enable_json,
    group,
    guard,
    is_json,
    is_quiet,
    out,
    state,
)

app = group("auth", "Проверка доступа: ключ шлюза 9router — `llm auth status`.")

RoutingOption = typer.Option(
    None, "--routing", help="Routing v1: JSON или файл; иначе LLMKIT_ROUTING_FILE, иначе файл по умолчанию."
)


def _routing(spec: str | None):
    """Routing для отчёта — необязателен: без него в отчёте нет ни одного провайдера."""
    spec = runtime.routing_spec(spec)
    if spec is None:
        return None
    return runtime.load_routing(spec, require_chain=False)


@app.command("status")
def status(
    ctx: typer.Context,
    check: bool = typer.Option(False, "--check", help="Сделать один дешёвый read-only вызов шлюза (лимит 10 с)."),
    provider: str = typer.Option(None, "--provider", help="Только этот провайдер (по умолчанию все)."),
    routing: str = RoutingOption,
    json_output: bool = JsonOption,
) -> None:
    """Показать доступ к шлюзу: откуда берётся ключ и работает ли он. Значение ключа не печатается.

    Провайдеры — из routing (`--routing`, LLMKIT_ROUTING_FILE или файл по
    умолчанию): у llmkit это шлюз 9router, подписки живут в нём. Без `--check`
    только наличие ключа (`unchecked` / `missing`); с ним — один бесплатный
    запрос `/models` шлюза с ключом. Модели не вызываются. Обязательных
    провайдеров у llmkit нет (`required: false`).
    Коды выхода: 0 — нет неверных ключей, 3 — ключ не принят
    (`error.code: CREDENTIALS_UNHEALTHY`, отчёт всё равно выводится),
    2 — неизвестный `--provider`. Форма `--json` — общий контракт инструментов:
    `tool`, `version`, `checked_at`, `credentials[]` с `provider`, `required`,
    `fields`, `source`, `source_ref`, `status`, `expires_at`, `quota`, `message`.

    Example: llm auth status --check --json
    """
    enable_json(ctx, json_output)
    with guard(ctx):
        loaded = _routing(routing)
        known = sorted(health.providers_of(loaded))
        if provider is not None and provider not in known:
            raise bad_arguments(f"провайдер {provider!r} не найден среди провайдеров с доступом: {', '.join(known)}")
        report = health.report(loaded, check=check, only=provider)
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
            "обновите переменную окружения с ключом шлюза и повторите",
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
