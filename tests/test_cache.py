"""Ключ кэша, TTL и восстановление типов."""

from __future__ import annotations

import time

from pydantic import BaseModel

from llmkit.cache import Cache, make_key
from llmkit.core import LlmKit


class Shape(BaseModel):
    name: str
    sides: int


BASE = {"messages": [{"role": "user", "content": "вопрос"}], "temperature": 0.0, "max_tokens": 100}


def test_key_depends_on_model_and_schema():
    first = make_key(model="openai/m1", **BASE)
    assert first != make_key(model="openai/m2", **BASE)
    assert first != make_key(model="openai/m1", schema={"type": "object"}, **BASE)
    assert first != make_key(model="openai/m1", **{**BASE, "temperature": 0.5})
    assert first == make_key(model="openai/m1", **BASE)


def test_pydantic_schema_changes_the_key():
    with_schema = make_key(model="openai/m1", schema=Shape, **BASE)
    assert with_schema != make_key(model="openai/m1", **BASE)
    assert with_schema == make_key(model="openai/m1", schema=Shape, **BASE)


def test_roundtrip_and_ttl(tmp_path):
    cache = Cache(tmp_path / "c.sqlite", ttl_days=30)
    cache.set("k", "openai/m1", {"x": 1})
    assert cache.get("k") == {"x": 1}
    # Протухшая запись не отдаётся и вычищается на старте нового экземпляра.
    with cache._connect() as connection:
        connection.execute("UPDATE cache SET created_at = ?", (time.time() - 31 * 86400,))
    assert cache.get("k") is None
    fresh = Cache(tmp_path / "c.sqlite", ttl_days=30)
    fresh._prepare()
    with fresh._connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM cache").fetchone()[0] == 0


def test_disabled_cache_is_a_no_op(tmp_path):
    cache = Cache(tmp_path / "c.sqlite", enabled=False)
    cache.set("k", "m", "ответ")
    assert cache.get("k") is None
    assert not (tmp_path / "c.sqlite").exists()


def test_decode_restores_pydantic_model():
    assert LlmKit._decode({"name": "куб", "sides": 6}, Shape) == Shape(name="куб", sides=6)
    assert LlmKit._decode({"name": "куб"}, {"type": "object"}) == {"name": "куб"}
    assert LlmKit._decode("текст", None) == "текст"
