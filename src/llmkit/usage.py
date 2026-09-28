"""Журнал вызовов, отчёты и бюджеты (раздел 8).

Одна строка на попытку. Отчёты группируются по меткам через
`json_extract(tags, '$.<метка>')`.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
import sqlite3
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .config import TAG_NAME_RE

SCHEMA = """
CREATE TABLE IF NOT EXISTS calls (
    id INTEGER PRIMARY KEY,
    ts REAL,
    task_id TEXT,
    tags TEXT,
    level TEXT,
    model TEXT,
    provider TEXT,
    status TEXT,
    error_type TEXT,
    attempt INTEGER,
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    cost_usd REAL,
    cost_known INTEGER,
    latency_ms INTEGER,
    pid INTEGER,
    served_model TEXT
);
CREATE INDEX IF NOT EXISTS calls_ts ON calls (ts);
CREATE INDEX IF NOT EXISTS calls_status ON calls (status);
"""

_SINCE_RE = re.compile(r"^(\d+)([dhw])$")


@dataclass
class Row:
    """Строка отчёта: метки группировки и агрегаты."""

    keys: dict[str, str | None] = field(default_factory=dict)
    calls: int = 0
    cached: int = 0
    failed: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0


def parse_since(since: datetime | str | None) -> float | None:
    """`datetime` | `"7d"` | None → unix-время начала периода."""
    if since is None:
        return None
    if isinstance(since, datetime):
        return since.timestamp()
    match = _SINCE_RE.match(since.strip().lower())
    if not match:
        raise ValueError(f"не понимаю период {since!r}: ожидается '7d', '12h', '2w' или datetime")
    amount, unit = int(match.group(1)), match.group(2)
    hours = {"h": 1, "d": 24, "w": 24 * 7}[unit] * amount
    return (datetime.now(UTC) - timedelta(hours=hours)).timestamp()


def _set_wal(connection: sqlite3.Connection) -> None:
    """WAL — режим файла, он живёт между запусками.

    Смена режима требует эксклюзивной блокировки и, в отличие от обычных
    запросов, не ждёт busy_timeout: если файл уже открыт другим процессом,
    SQLite сразу отвечает "database is locked". Режим при этом уже такой,
    какой нужно, поэтому ошибку глотаем.
    """
    with contextlib.suppress(sqlite3.OperationalError):
        connection.execute("PRAGMA journal_mode=WAL")


class Usage:
    """Журнал вызовов в SQLite."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._ready = False
        self._lock = threading.Lock()

    @contextmanager
    def _connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=5.0)
        try:
            # Ждать блокировку, а не падать: базу пишут несколько процессов.
            connection.execute("PRAGMA busy_timeout=5000")
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _prepare(self) -> None:
        if self._ready:
            return
        with self._lock:
            if self._ready:  # успели, пока ждали лок
                return
            with self._connect() as connection:
                _set_wal(connection)
                connection.executescript(SCHEMA)
                columns = {row[1] for row in connection.execute("PRAGMA table_info(calls)")}
                if "served_model" not in columns:
                    # База до v0.4.2. Соседний процесс мог добавить колонку первым — не ошибка.
                    with contextlib.suppress(sqlite3.OperationalError):
                        connection.execute("ALTER TABLE calls ADD COLUMN served_model TEXT")
            self._ready = True

    def record(
        self,
        *,
        model: str,
        provider: str,
        status: str,
        attempt: int = 0,
        task_id: str | None = None,
        tags: dict[str, str] | None = None,
        level: str | None = None,
        error_type: str | None = None,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        cost_usd: float = 0.0,
        cost_known: bool = True,
        latency_ms: int = 0,
        served_model: str | None = None,
    ) -> None:
        self._prepare()
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO calls (ts, task_id, tags, level, model, provider, status, error_type, attempt,"
                " prompt_tokens, completion_tokens, cost_usd, cost_known, latency_ms, pid, served_model)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    time.time(),
                    task_id,
                    json.dumps(tags or {}, ensure_ascii=False),
                    level,
                    model,
                    provider,
                    status,
                    error_type,
                    attempt,
                    prompt_tokens,
                    completion_tokens,
                    cost_usd,
                    int(cost_known),
                    latency_ms,
                    os.getpid(),
                    served_model,
                ),
            )

    async def arecord(self, **kwargs: Any) -> None:
        await asyncio.to_thread(lambda: self.record(**kwargs))

    def _window(self, since: datetime | str | None, until: datetime | str | None) -> tuple[str, list[Any]]:
        where, params = [], []
        start = parse_since(since)
        if start is not None:
            where.append("ts >= ?")
            params.append(start)
        end = parse_since(until)
        if end is not None:
            where.append("ts <= ?")
            params.append(end)
        return (" WHERE " + " AND ".join(where) if where else ""), params

    _AGGREGATES = (
        "COUNT(*), SUM(status = 'cache'), SUM(status = 'failed'),"
        " COALESCE(SUM(prompt_tokens), 0), COALESCE(SUM(completion_tokens), 0), COALESCE(SUM(cost_usd), 0)"
    )

    @staticmethod
    def _json_extract(name: str) -> str:
        """Фрагмент SQL для метки; имя проверяется, значения идут параметрами."""
        if not TAG_NAME_RE.match(name):
            raise ValueError(f"имя метки должно быть [A-Za-z0-9_], получено {name!r}")
        return "json_extract(tags, '$." + name + "')"

    def report(
        self,
        group_by: tuple[str, ...] | list[str] = (),
        since: datetime | str | None = None,
        until: datetime | str | None = None,
    ) -> list[Row]:
        """Агрегаты по меткам за период; без `group_by` — одна общая строка."""
        self._prepare()
        group_by = tuple(group_by)
        selects = [self._json_extract(name) for name in group_by]
        where, params = self._window(since, until)
        columns = ", ".join([*selects, self._AGGREGATES])
        # Имена меток уже проверены в _json_extract, значения идут параметрами.
        query = "SELECT " + columns + " FROM calls" + where  # noqa: S608
        if selects:
            query += " GROUP BY " + ", ".join(str(i + 1) for i in range(len(selects)))
            query += f" ORDER BY {len(selects) + 6} DESC"
        with self._connect() as connection:
            raw = connection.execute(query, params).fetchall()
        rows = []
        for record in raw:
            values, aggregates = record[: len(group_by)], record[len(group_by) :]
            rows.append(
                Row(
                    keys=dict(zip(group_by, values, strict=True)),
                    calls=aggregates[0] or 0,
                    cached=aggregates[1] or 0,
                    failed=aggregates[2] or 0,
                    prompt_tokens=aggregates[3] or 0,
                    completion_tokens=aggregates[4] or 0,
                    cost_usd=float(aggregates[5] or 0.0),
                )
            )
        return rows

    def total(self, since: datetime | str | None = None, until: datetime | str | None = None) -> Row:
        rows = self.report((), since=since, until=until)
        return rows[0] if rows else Row()

    def spent_today(self, tag: str | None = None) -> float:
        """Потрачено с начала текущих суток UTC; `tag` — строка `метка=значение`."""
        self._prepare()
        start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        query = "SELECT COALESCE(SUM(cost_usd), 0) FROM calls WHERE ts >= ?"
        params: list[Any] = [start]
        if tag:
            name, _, value = tag.partition("=")
            query += " AND " + self._json_extract(name) + " = ?"
            params.append(value)
        with self._connect() as connection:
            return float(connection.execute(query, params).fetchone()[0] or 0.0)

    async def aspent_today(self, tag: str | None = None) -> float:
        return await asyncio.to_thread(self.spent_today, tag)
