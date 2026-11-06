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


_HOURS = {"h": 1, "d": 24, "w": 168}


def _stamp(moment: datetime) -> str:
    """Момент строкой того же вида, что `timestamp` шлюза (ISO 8601 UTC)."""
    return moment.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _moment(value: str | datetime) -> datetime:
    """Момент из смещения назад (`7d`, `12h`, `2w`) или даты ISO 8601 (`2026-11-01`)."""
    if isinstance(value, datetime):
        return value
    text = value.strip()
    unit = text[-1:].lower()
    if text[:-1].isdigit() and unit in _HOURS:
        return datetime.now(UTC) - timedelta(hours=_HOURS[unit] * int(text[:-1]))
    try:
        return datetime.fromisoformat(text.upper()).replace(tzinfo=UTC)
    except ValueError:
        raise ValueError(f"не понимаю период {value!r}: ожидается '7d', '12h', '2w' или дата") from None


def _bound(value: str | datetime | None, *, end: bool) -> str:
    """Граница периода; пустая строка — без границы. Дата без времени закрывает весь день."""
    if value is None:
        return "9999" if end else ""
    moment = _moment(value)
    if end and not isinstance(value, datetime) and len(value.strip()) == 10:
        moment += timedelta(days=1)
    return _stamp(moment)


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
    target = journal_path(path)
    try:
        connection = _open(target)
        try:
            raw = connection.execute(
                "SELECT apiKey, COUNT(*), COALESCE(SUM(promptTokens), 0), COALESCE(SUM(completionTokens), 0),"
                " COALESCE(SUM(cost), 0) FROM usageHistory WHERE timestamp >= ? AND timestamp <= ?"
                " GROUP BY apiKey ORDER BY 5 DESC",
                (_bound(since, end=False), _bound(until, end=True)),
            ).fetchall()
        finally:
            connection.close()
    except sqlite3.Error as exc:
        raise JournalUnavailable(target, str(exc)) from exc
    return [
        Row(key=key, calls=calls, prompt_tokens=into, completion_tokens=out, cost_usd=float(cost))
        for key, calls, into, out, cost in raw
    ]
