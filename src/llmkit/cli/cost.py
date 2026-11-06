"""Команда `llm cost`: расходы из журнала шлюза 9router (только чтение)."""

import typer
from rich.table import Table

from .. import usage
from .app import app
from .output import CliError, JsonOption, bad_arguments, emit, enable_json, guard, out

PERIOD_HINT = "ожидается 7d, 12h, 2w или ГГГГ-ММ-ДД"


def _row_payload(row: usage.Row) -> dict:
    return {
        "key": row.key,
        "calls": row.calls,
        "prompt_tokens": row.prompt_tokens,
        "completion_tokens": row.completion_tokens,
        "cost_usd": round(row.cost_usd, 6),
    }


@app.command("cost")
def cost(
    ctx: typer.Context,
    since: str = typer.Option(None, "--since", help="Начало периода: 7d, 12h, 2w или ГГГГ-ММ-ДД."),
    until: str = typer.Option(None, "--until", help="Конец периода в том же формате."),
    json_output: bool = JsonOption,
) -> None:
    """Показать расходы из журнала шлюза по ключам потребителей.

    Журнал шлюза (`usageHistory`) открывается только на чтение: путь —
    `LLMKIT_GATEWAY_DB`, по умолчанию `~/.9router/db/data.sqlite`. Строки — по
    ключу шлюза, от большего расхода к меньшему; `total` — сумма по всем. На
    пустом журнале — пустая таблица и код выхода 0. Коды выхода: 0 — готово,
    2 — неверный период, 5 — журнала нет или он не читается (`error.path`).

    Example: llm cost --since 7d --json
    """
    enable_json(ctx, json_output)
    with guard(ctx):
        try:
            rows = usage.report(since=since, until=until)
        except ValueError as exc:
            raise bad_arguments(str(exc), PERIOD_HINT) from exc
        except usage.JournalUnavailable as exc:
            raise CliError(
                "GATEWAY_DB_UNAVAILABLE",
                str(exc),
                f"задайте путь к журналу шлюза: `export {usage.ENV_VAR}=/путь/к/data.sqlite`",
                exit_code=5,
                details={"path": str(exc.path)},
            ) from exc
        total = usage.Row(
            calls=sum(row.calls for row in rows),
            prompt_tokens=sum(row.prompt_tokens for row in rows),
            completion_tokens=sum(row.completion_tokens for row in rows),
            cost_usd=sum(row.cost_usd for row in rows),
        )

        def render() -> None:
            table = Table(title="Расходы шлюза")
            for column in ("Ключ", "Вызовов", "Токены", "$"):
                table.add_column(column, justify="left" if column == "Ключ" else "right")
            for row in rows:
                table.add_row(
                    row.key or "—",
                    str(row.calls),
                    f"{row.prompt_tokens}/{row.completion_tokens}",
                    f"{row.cost_usd:.6f}",
                )
            table.add_row(
                "итого", str(total.calls), f"{total.prompt_tokens}/{total.completion_tokens}", f"{total.cost_usd:.6f}"
            )
            out.print(table)

        emit(ctx, {"rows": [_row_payload(row) for row in rows], "total": _row_payload(total)}, render)
