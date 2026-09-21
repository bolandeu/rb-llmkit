"""SQLite-кэш ответов (раздел 7).

Ключ считается по конкретной модели попытки, а не по уровню: ответ дешёвой
модели не выдаётся за ответ сильной.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS cache (
    key TEXT PRIMARY KEY,
    model TEXT,
    created_at REAL,
    response TEXT
)
"""


def schema_fingerprint(schema: Any) -> Any:
    """Стабильное представление схемы для ключа кэша."""
    if schema is None:
        return None
    dump = getattr(schema, "model_json_schema", None)
    if callable(dump):
        return dump()
    return schema


def make_key(
    *,
    model: str,
    messages: list[dict],
    schema: Any = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> str:
    payload = {
        "model": model,
        "messages": messages,
        "schema": schema_fingerprint(schema),
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _set_wal(connection: sqlite3.Connection) -> None:
    """WAL — режим файла, он живёт между запусками.

    Смена режима требует эксклюзивной блокировки и, в отличие от обычных
    запросов, не ждёт busy_timeout: если файл уже открыт другим процессом,
    SQLite сразу отвечает "database is locked". Режим при этом уже такой,
    какой нужно, поэтому ошибку глотаем.
    """
    with contextlib.suppress(sqlite3.OperationalError):
        connection.execute("PRAGMA journal_mode=WAL")


class Cache:
    """Таблица `cache` в SQLite; несколько процессов — через WAL."""

    def __init__(self, path: Path, *, ttl_days: int = 30, enabled: bool = True) -> None:
        self.path = Path(path)
        self.ttl_seconds = max(ttl_days, 0) * 86400
        self.enabled = enabled
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
        """Создать таблицу и выкинуть протухшее — один раз на экземпляр."""
        if self._ready:
            return
        with self._lock, self._connect() as connection:
            if self._ready:
                return
            _set_wal(connection)
            connection.execute(SCHEMA)
            if self.ttl_seconds:
                connection.execute("DELETE FROM cache WHERE created_at < ?", (time.time() - self.ttl_seconds,))
        self._ready = True

    def get(self, key: str) -> Any | None:
        if not self.enabled:
            return None
        self._prepare()
        with self._connect() as connection:
            row = connection.execute("SELECT created_at, response FROM cache WHERE key = ?", (key,)).fetchone()
        if row is None:
            return None
        created_at, response = row
        if self.ttl_seconds and created_at < time.time() - self.ttl_seconds:
            return None
        try:
            return json.loads(response)
        except ValueError:
            return None

    def set(self, key: str, model: str, value: Any) -> None:
        if not self.enabled:
            return
        self._prepare()
        payload = json.dumps(value, ensure_ascii=False, default=str)
        with self._connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO cache (key, model, created_at, response) VALUES (?, ?, ?, ?)",
                (key, model, time.time(), payload),
            )

    async def aget(self, key: str) -> Any | None:
        return await asyncio.to_thread(self.get, key)

    async def aset(self, key: str, model: str, value: Any) -> None:
        await asyncio.to_thread(self.set, key, model, value)
