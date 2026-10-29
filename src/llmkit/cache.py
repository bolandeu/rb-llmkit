"""Кэш ответов в базе журнала (раздел 7).

Ключ считается по конкретной модели попытки, а не по уровню: ответ дешёвой
модели не выдаётся за ответ сильной.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import threading
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover
    import sqlalchemy as sa


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
    api_base: str | None = None,
    schema: Any = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> str:
    """Ключ по ссылке `провайдер/модель` и адресу провайдера.

    Именно `provider/model`, а не имя модели для LiteLLM: одна и та же
    модель у ollama.com и у localhost — разные ответы и разные ключи.
    Ключ провайдера в подпись не входит.
    """
    payload = {
        "model": model,
        "api_base": api_base,
        "messages": messages,
        "schema": schema_fingerprint(schema),
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


class Cache:
    """Таблица `llmkit_cache` в базе журнала: общая PostgreSQL или локальная SQLite.

    `engine` отдаёт открытую базу (её держит `Usage`). Первая запись по ключу
    остаётся: повторная вставка молча пропускается.
    """

    def __init__(self, engine: Callable[[], sa.Engine], *, ttl_days: int = 30, enabled: bool = True) -> None:
        self._engine = engine
        self.ttl_seconds = max(ttl_days, 0) * 86400
        self.enabled = enabled
        self._ready = False
        self._lock = threading.Lock()

    def _expired(self) -> Any:
        from .db.tables import cache

        return cache.c.created_at < time.time() - self.ttl_seconds

    def _prepare(self) -> None:
        """Выкинуть протухшее — один раз на экземпляр."""
        if self._ready:
            return
        with self._lock:
            if self._ready:  # успели, пока ждали лок
                return
            if self.ttl_seconds:
                self._delete_expired()
            self._ready = True

    def _delete_expired(self) -> None:
        import sqlalchemy as sa

        from .db.tables import cache

        with self._engine().begin() as connection:
            connection.execute(sa.delete(cache).where(self._expired()))

    def get(self, key: str) -> Any | None:
        if not self.enabled:
            return None
        import sqlalchemy as sa

        from .db.tables import cache

        self._prepare()
        with self._engine().connect() as connection:
            row = connection.execute(sa.select(cache.c.created_at, cache.c.response).where(cache.c.key == key)).first()
        if row is None:
            return None
        created_at, response = row
        if self.ttl_seconds and created_at < time.time() - self.ttl_seconds:
            self._delete_expired()
            return None
        try:
            return json.loads(response)
        except ValueError:
            return None

    def set(self, key: str, model: str, value: Any) -> None:
        if not self.enabled:
            return

        from .db.tables import cache

        self._prepare()
        payload = json.dumps(value, ensure_ascii=False, default=str)
        values = {"key": key, "model": model, "created_at": time.time(), "response": payload}
        with self._engine().begin() as connection:
            if connection.dialect.name == "postgresql":
                from sqlalchemy.dialects.postgresql import insert
            else:
                from sqlalchemy.dialects.sqlite import insert
            connection.execute(insert(cache).values(**values).on_conflict_do_nothing(index_elements=["key"]))

    async def aget(self, key: str) -> Any | None:
        return await asyncio.to_thread(self.get, key)

    async def aset(self, key: str, model: str, value: Any) -> None:
        await asyncio.to_thread(self.set, key, model, value)

    async def aget_safe(self, key: str, warnings: list[str]) -> Any | None:
        """Сбой базы кэша — промах и предупреждение, вызов не падает."""
        try:
            return await self.aget(key)
        except Exception as exc:
            warnings.append(f"cache: чтение не удалось ({type(exc).__name__}), вызов идёт к провайдеру")
            return None

    async def aset_safe(self, key: str, model: str, value: Any, warnings: list[str]) -> None:
        try:
            await self.aset(key, model, value)
        except Exception as exc:
            warnings.append(f"cache: запись не удалась ({type(exc).__name__}), ответ не сохранён")
