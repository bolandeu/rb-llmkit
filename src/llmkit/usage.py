"""Журнал расходов шлюза 9router — только чтение (`llm cost`).

Своего журнала у llmkit нет: расходы пишет шлюз в свою SQLite — таблица
`usageHistory`, строка на запрос (колонки `timestamp` ISO 8601 UTC, `apiKey`,
`promptTokens`, `completionTokens`, `cost`). llmkit открывает файл на чтение
(`mode=ro`) и никогда не пишет и не мигрирует его. Потребителя различает ключ
шлюза из `apiKey`. Путь — `LLMKIT_GATEWAY_DB`, по умолчанию `~/.9router/db/data.sqlite`.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

ENV_VAR = "LLMKIT_GATEWAY_DB"
DEFAULT_PATH = Path("~/.9router/db/data.sqlite")


class JournalUnavailable(Exception):
    """Журнала шлюза нет или он не читается: `path` называет файл."""

    def __init__(self, path: Path, reason: str) -> None:
        self.path = path
        self.reason = reason
        super().__init__(f"журнал шлюза не читается: {path} ({reason})")


@dataclass
class Row:
    """Строка отчёта: ключ шлюза и суммы за период."""

    key: str | None = None
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0


def journal_path(path: Path | str | None = None) -> Path:
    """Путь журнала: аргумент → `LLMKIT_GATEWAY_DB` → `~/.9router/db/data.sqlite`."""
    if path:
        return Path(path).expanduser()
    import os

    return Path(os.environ.get(ENV_VAR) or DEFAULT_PATH).expanduser()


def _since(value: str | datetime) -> str:
    """Начало периода строкой того же вида, что `timestamp` шлюза (ISO 8601 UTC)."""
    if isinstance(value, datetime):
        moment = value
    else:
        text = value.strip().lower()
        amount, unit = text[:-1], text[-1:]
        if not amount.isdigit() or unit not in ("h", "d", "w"):
            raise ValueError(f"не понимаю период {value!r}: ожидается '7d', '12h', '2w' или дата")
        moment = datetime.now(UTC) - timedelta(hours={"h": 1, "d": 24, "w": 168}[unit] * int(amount))
    return moment.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _open(path: Path) -> sqlite3.Connection:
    """Файл шлюза — только на чтение: ни журнала транзакций, ни -wal рядом не появляется."""
    if not path.is_file():
        raise JournalUnavailable(path, "файла нет")
    try:
        return sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        raise JournalUnavailable(path, str(exc)) from exc


# Границы периода — параметрами; пустая строка вместо границы означает «без границы»:
# timestamp шлюза — ISO 8601, сравнение строкой и есть сравнение времени.


def report(
    *, since: str | datetime | None = None, until: str | datetime | None = None, path: Path | str | None = None
) -> list[Row]:
    """Расходы за период по ключам шлюза, от большего к меньшему; без периода — за всё время."""
    start = _since(since) if since is not None else ""
    end = _since(until) if until is not None else "9999"
    target = journal_path(path)
    try:
        with _open(target) as connection:
            raw = connection.execute(
                "SELECT apiKey, COUNT(*), COALESCE(SUM(promptTokens), 0), COALESCE(SUM(completionTokens), 0),"
                " COALESCE(SUM(cost), 0) FROM usageHistory WHERE timestamp >= ? AND timestamp <= ?"
                " GROUP BY apiKey ORDER BY 5 DESC",
                (start, end),
            ).fetchall()
    except sqlite3.Error as exc:
        raise JournalUnavailable(target, str(exc)) from exc
    return [
        Row(key=key, calls=calls, prompt_tokens=into, completion_tokens=out, cost_usd=float(cost))
        for key, calls, into, out, cost in raw
    ]


def total(
    *, since: str | datetime | None = None, until: str | datetime | None = None, path: Path | str | None = None
) -> Row:
    """Сумма по всем ключам за период."""
    rows = report(since=since, until=until, path=path)
    return Row(
        calls=sum(row.calls for row in rows),
        prompt_tokens=sum(row.prompt_tokens for row in rows),
        completion_tokens=sum(row.completion_tokens for row in rows),
        cost_usd=sum(row.cost_usd for row in rows),
    )
