"""Ключ кэша, TTL и восстановление типов."""

from __future__ import annotations

import time
from typing import Any

import sqlalchemy as sa
from conftest import ROUTING, FakeCompletion, response
from pydantic import BaseModel

from llmkit import Task
from llmkit.cache import Cache, make_key
from llmkit.core import LlmKit
from llmkit.db.tables import cache as cache_table
from llmkit.usage import Usage


class Shape(BaseModel):
    name: str
    sides: int


BASE: dict[str, Any] = {"messages": [{"role": "user", "content": "вопрос"}], "temperature": 0.0, "max_tokens": 100}


def test_key_depends_on_model_and_schema():
    first = make_key(model="openai/m1", **BASE)
    assert first != make_key(model="openai/m2", **BASE)
    assert first != make_key(model="openai/m1", schema={"type": "object"}, **BASE)
    hot: dict[str, Any] = {**BASE, "temperature": 0.5}
    assert first != make_key(model="openai/m1", **hot)
    assert first == make_key(model="openai/m1", **BASE)


def test_pydantic_schema_changes_the_key():
    with_schema = make_key(model="openai/m1", schema=Shape, **BASE)
    assert with_schema != make_key(model="openai/m1", **BASE)
    assert with_schema == make_key(model="openai/m1", schema=Shape, **BASE)


def _cache(tmp_path, **kwargs) -> Cache:
    """Кэш в базе журнала: тот же файл, что открывает `Usage`."""
    return Cache(Usage(tmp_path / "u.sqlite")._db, **kwargs)


def _age_all(cache: Cache, days: int) -> None:
    with cache._engine().begin() as connection:
        connection.execute(sa.update(cache_table).values(created_at=time.time() - days * 86400))


def _rows(cache: Cache) -> int:
    with cache._engine().connect() as connection:
        return connection.execute(sa.select(sa.func.count()).select_from(cache_table)).scalar_one()


def test_roundtrip_and_ttl(tmp_path):
    cache = _cache(tmp_path, ttl_days=30)
    cache.set("k", "openai/m1", {"x": 1})
    assert cache.get("k") == {"x": 1}
    _age_all(cache, 31)
    assert cache.get("k") is None
    assert _rows(cache) == 0


def test_expired_rows_are_deleted_on_start(tmp_path):
    cache = _cache(tmp_path, ttl_days=30)
    cache.set("k", "openai/m1", "старый")
    _age_all(cache, 31)
    fresh = _cache(tmp_path, ttl_days=30)
    fresh.set("other", "openai/m1", "новый")
    assert _rows(fresh) == 1


def test_first_write_wins(tmp_path):
    first, second = _cache(tmp_path), _cache(tmp_path)
    first.set("k", "openai/m1", "первый")
    second.set("k", "openai/m1", "второй")
    assert first.get("k") == "первый"
    assert second.get("k") == "первый"
    assert _rows(first) == 1


def test_disabled_cache_is_a_no_op(tmp_path):
    cache = _cache(tmp_path, enabled=False)
    cache.set("k", "m", "ответ")
    assert cache.get("k") is None
    assert not (tmp_path / "u.sqlite").exists()


async def test_second_kit_on_one_database_hits_the_first_answer():
    first = LlmKit(routing=ROUTING, completion=FakeCompletion([response("первый")]))
    second_fake = FakeCompletion([response("второй")])
    second = LlmKit(routing=ROUTING, completion=second_fake)
    asked = await first.ask(Task(user="вопрос"))
    hit = await second.ask(Task(user="вопрос"))
    assert asked.source == "llm"
    assert hit.source == "cache" and hit.data == "первый" and hit.cost_usd == 0.0
    assert second_fake.calls == []


async def test_old_cache_file_is_ignored(isolated):
    old = isolated / "cache.sqlite"
    old.write_bytes(b"not a database at all")
    fake = FakeCompletion([response("ответ")])
    answer = await LlmKit(routing=ROUTING, completion=fake).ask(Task(user="вопрос"))
    assert answer.source == "llm" and answer.warnings == []
    assert old.read_bytes() == b"not a database at all"


def test_decode_restores_pydantic_model():
    assert LlmKit._decode({"name": "куб", "sides": 6}, Shape) == Shape(name="куб", sides=6)
    assert LlmKit._decode({"name": "куб"}, {"type": "object"}) == {"name": "куб"}
    assert LlmKit._decode("текст", None) == "текст"


def test_key_depends_on_api_base():
    """Одна модель у разных адресов провайдера — разные записи кэша."""
    cloud = make_key(model="ollama/gpt-oss:120b", api_base="https://ollama.com", **BASE)
    local = make_key(model="ollama/gpt-oss:120b", api_base="http://localhost:11434", **BASE)
    assert cloud != local
    assert cloud == make_key(model="ollama/gpt-oss:120b", api_base="https://ollama.com", **BASE)
