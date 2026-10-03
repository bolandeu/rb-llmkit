"""Журнал вызовов, отчёты и бюджеты (раздел 8).

Одна строка на попытку, таблица `llmkit_calls` в базе llmkit (`llmkit.db`):
общая PostgreSQL, если задан `LLMKIT_DATABASE_URL`, иначе локальная SQLite
(`usage.sqlite`). Отчёты группируются по меткам из JSON-колонки `tags`.
"""

from __future__ import annotations

import asyncio
import os
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .config import TAG_NAME_RE

if TYPE_CHECKING:  # pragma: no cover
    import sqlalchemy as sa

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


class Usage:
    """Журнал вызовов: `path` — локальная SQLite, когда `LLMKIT_DATABASE_URL` не задан."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._engine: sa.Engine | None = None
        self._lock = threading.Lock()

    def _db(self) -> sa.Engine:
        """База открывается при первом обращении: SQLite мигрируется, PostgreSQL сверяется."""
        if self._engine is None:
            with self._lock:
                if self._engine is None:  # успели, пока ждали лок
                    from . import db

                    self._engine = db.open_db(self.path)
        return self._engine

    def close(self) -> None:
        with self._lock:
            if self._engine is not None:
                self._engine.dispose()
                self._engine = None

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
        cost_source: str | None = None,
        billable: bool = False,
        latency_ms: int = 0,
        served_model: str | None = None,
    ) -> None:
        import sqlalchemy as sa

        from .db.tables import calls

        with self._db().begin() as connection:
            connection.execute(
                sa.insert(calls).values(
                    ts=time.time(),
                    task_id=task_id,
                    tags=tags or {},
                    level=level,
                    model=model,
                    provider=provider,
                    status=status,
                    error_type=error_type,
                    attempt=attempt,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    cost_usd=cost_usd,
                    cost_known=int(cost_known),
                    cost_source=cost_source,
                    billable=int(billable),
                    latency_ms=latency_ms,
                    pid=os.getpid(),
                    served_model=served_model,
                )
            )

    async def arecord(self, **kwargs: Any) -> None:
        await asyncio.to_thread(lambda: self.record(**kwargs))

    @staticmethod
    def _window(since: datetime | str | None, until: datetime | str | None) -> list[Any]:
        from .db.tables import calls

        where = []
        start = parse_since(since)
        if start is not None:
            where.append(calls.c.ts >= start)
        end = parse_since(until)
        if end is not None:
            where.append(calls.c.ts <= end)
        return where

    @staticmethod
    def _tag(name: str):
        """Значение метки из JSON `tags`; имя проверяется, хотя в SQL оно идёт параметром."""
        from .db.tables import calls

        if not TAG_NAME_RE.match(name):
            raise ValueError(f"имя метки должно быть [A-Za-z0-9_], получено {name!r}")
        return calls.c.tags[name].as_string()

    def report(
        self,
        group_by: tuple[str, ...] | list[str] = (),
        since: datetime | str | None = None,
        until: datetime | str | None = None,
    ) -> list[Row]:
        """Агрегаты по меткам за период; без `group_by` — одна общая строка."""
        import sqlalchemy as sa

        from .db.tables import calls

        group_by = tuple(group_by)
        keys = [self._tag(name).label(f"k{i}") for i, name in enumerate(group_by)]
        cost = sa.func.coalesce(sa.func.sum(calls.c.cost_usd), 0)
        query = sa.select(
            *keys,
            sa.func.count(),
            sa.func.sum(sa.case((calls.c.status == "cache", 1), else_=0)),
            sa.func.sum(sa.case((calls.c.status == "failed", 1), else_=0)),
            sa.func.coalesce(sa.func.sum(calls.c.prompt_tokens), 0),
            sa.func.coalesce(sa.func.sum(calls.c.completion_tokens), 0),
            cost,
        ).where(*self._window(since, until))
        if keys:
            query = query.group_by(*keys).order_by(cost.desc())
        with self._db().connect() as connection:
            raw = connection.execute(query).all()
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
        import sqlalchemy as sa

        from .db.tables import calls

        start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        query = sa.select(sa.func.coalesce(sa.func.sum(calls.c.cost_usd), 0)).where(calls.c.ts >= start)
        if tag:
            name, _, value = tag.partition("=")
            query = query.where(self._tag(name) == value)
        with self._db().connect() as connection:
            return float(connection.execute(query).scalar_one() or 0.0)

    async def aspent_today(self, tag: str | None = None) -> float:
        return await asyncio.to_thread(self.spent_today, tag)
