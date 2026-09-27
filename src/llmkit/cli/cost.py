"""Команда `llm cost`: отчёт о расходах из журнала вызовов."""

from datetime import UTC, datetime

import typer
from rich.table import Table

from .. import config as config_mod
from ..usage import Usage
from .app import app
from .output import JsonOption, bad_arguments, emit, enable_json, guard, out


def _period(value: str | None, what: str):
    """`7d` отдаём журналу как есть, `ГГГГ-ММ-ДД` превращаем в дату."""
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=UTC)
    except ValueError:
        pass
    if value[:-1].isdigit() and value[-1] in "dhw":
        return value
    raise bad_arguments(f"не понимаю {what}={value!r}", "ожидается 7d, 12h, 2w или ГГГГ-ММ-ДД")


def _row_payload(row) -> dict:
    return {
        "keys": row.keys,
        "calls": row.calls,
        "cached": row.cached,
        "failed": row.failed,
        "prompt_tokens": row.prompt_tokens,
        "completion_tokens": row.completion_tokens,
        "cost_usd": round(row.cost_usd, 6),
    }


@app.command("cost")
def cost(
    ctx: typer.Context,
    by: str = typer.Option(None, "--by", help="Метки для группировки через запятую, например tool,niche."),
    since: str = typer.Option(None, "--since", help="Начало периода: 7d, 12h, 2w или ГГГГ-ММ-ДД."),
    until: str = typer.Option(None, "--until", help="Конец периода в том же формате."),
    json_output: bool = JsonOption,
) -> None:
    """Показать расходы из журнала вызовов.

    Без `--by` печатается одна итоговая строка. На пустом журнале — пустая
    таблица и код выхода 0; 2 — неверный период.

    Example: llm cost --by tool --since 7d
    """
    enable_json(ctx, json_output)
    with guard(ctx):
        group_by = tuple(name.strip() for name in by.split(",") if name.strip()) if by else ()
        start, end = _period(since, "--since"), _period(until, "--until")
        journal = Usage(config_mod.load().usage_path())
        rows = journal.report(group_by, since=start, until=end) if group_by else []
        total = journal.total(since=start, until=end)

        def render() -> None:
            table = Table(title="Расходы")
            for name in group_by:
                table.add_column(name)
            for column in ("вызовов", "из кэша", "ошибок", "токены", "$"):
                table.add_column(column, justify="right")
            for row in rows:
                table.add_row(
                    *[str(row.keys.get(name) or "—") for name in group_by],
                    str(row.calls),
                    str(row.cached),
                    str(row.failed),
                    f"{row.prompt_tokens}/{row.completion_tokens}",
                    f"{row.cost_usd:.6f}",
                )
            labels = ["итого"] + [""] * (len(group_by) - 1) if group_by else []
            table.add_row(
                *labels,
                str(total.calls),
                str(total.cached),
                str(total.failed),
                f"{total.prompt_tokens}/{total.completion_tokens}",
                f"{total.cost_usd:.6f}",
            )
            out.print(table)

        emit(ctx, {"rows": [_row_payload(row) for row in rows], "total": _row_payload(total)}, render)
