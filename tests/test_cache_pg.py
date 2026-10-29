"""Общий кэш на PostgreSQL: несколько процессов, одна база (запуск — scripts/pg_test.sh)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
import sqlalchemy as sa

from llmkit import db

PG_URL = os.environ.get("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(not PG_URL, reason="TEST_DATABASE_URL не задан")

# Дочерний процесс — отдельный воркер: свой LlmKit, фейковый провайдер вместо сети.
# Ждёт общего момента старта, чтобы оба вызова шли одновременно (ответ провайдера — через паузу).
WORKER = """
import asyncio, json, os, time

from llmkit import LlmKit, Task

routing = {
    "providers": {"a": {"protocol": "openai_compatible", "base_url": "http://localhost:11111/v1", "key_env": "WORKER_KEY"}},
    "chain": ["a/m1"],
}
calls = []


async def completion(**kwargs):
    from types import SimpleNamespace

    calls.append(kwargs["model"])
    await asyncio.sleep(0.5)
    return SimpleNamespace(
        model="fake",
        choices=[SimpleNamespace(message=SimpleNamespace(content="общий ответ"), finish_reason="stop")],
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
    )


async def main():
    time.sleep(max(0.0, float(os.environ["WORKER_START_AT"]) - time.time()))
    answer = await LlmKit(routing=routing, completion=completion).ask(Task(user="один вопрос"))
    print(json.dumps({"data": answer.data, "source": answer.source, "cost_usd": answer.cost_usd, "provider_calls": len(calls)}))


asyncio.run(main())
"""


@pytest.fixture
def engine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    assert PG_URL
    # Тест удаляет таблицы llmkit: только одноразовый локальный сервер.
    assert sa.make_url(PG_URL).host in ("127.0.0.1", "localhost"), "TEST_DATABASE_URL — только из scripts/pg_test.sh"
    monkeypatch.setenv(db.ENV_VAR, PG_URL)
    pg = db.open_db(check=False)
    with pg.begin() as conn:  # с чистого листа: только объекты llmkit
        conn.execute(sa.text("DROP VIEW IF EXISTS llmkit_v1_calls"))
        conn.execute(sa.text(f"DROP TABLE IF EXISTS llmkit_calls, llmkit_cache, {db.VERSION_TABLE}"))
    assert db.upgrade(pg).up_to_date
    yield pg
    pg.dispose()


def _start_workers(tmp_path: Path, count: int) -> list[dict]:
    """`count` процессов одновременно спрашивают один и тот же вызов; ответы — в порядке запуска."""
    assert PG_URL
    env = {
        **os.environ,
        db.ENV_VAR: PG_URL,
        "WORKER_KEY": "ключ",
        "WORKER_START_AT": str(time.time() + 3),  # к этому моменту все процессы уже импортировали llmkit
        "HOME": str(tmp_path),
        "XDG_CONFIG_HOME": str(tmp_path / "config"),
        "XDG_DATA_HOME": str(tmp_path / "data"),
    }
    env.pop("LLMKIT_CACHE", None)
    workers = [
        subprocess.Popen(  # noqa: S603 - свой интерпретатор и свой код
            [sys.executable, "-I", "-c", WORKER], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        for _ in range(count)
    ]
    results = []
    for worker in workers:
        out, err = worker.communicate(timeout=60)
        assert worker.returncode == 0, err
        results.append(json.loads(out.splitlines()[-1]))
    return results


def _count(engine: sa.Engine, query: str) -> int:
    with engine.connect() as conn:
        return conn.execute(sa.text(query)).scalar_one()


def test_two_workers_asking_at_once_share_one_cache_row(tmp_path: Path, engine: sa.Engine) -> None:
    first, second = _start_workers(tmp_path, 2)
    assert first["data"] == second["data"] == "общий ответ"
    assert _count(engine, "SELECT count(*) FROM llmkit_cache") == 1


def test_third_worker_gets_a_free_hit_from_the_same_database(tmp_path: Path, engine: sa.Engine) -> None:
    (stored,) = _start_workers(tmp_path, 1)
    assert stored["source"] == "llm" and stored["provider_calls"] == 1

    (third,) = _start_workers(tmp_path, 1)
    assert third["data"] == "общий ответ"
    assert third["source"] == "cache" and third["cost_usd"] == 0 and third["provider_calls"] == 0
    assert _count(engine, "SELECT count(*) FROM llmkit_calls WHERE status = 'cache'") == 1
    assert _count(engine, "SELECT count(*) FROM llmkit_cache") == 1
