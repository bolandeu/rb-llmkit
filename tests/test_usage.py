"""Своего состояния нет: завершённый вызов не пишет ни строки, ни файла, и кэша в контракте нет.

`ask` ходит только в шлюз: ни журнала расходов, ни кэша ответов — ни файла, ни
таблицы. `LLMKIT_DATABASE_URL` не читается; в `--json` нет `cache_hit`, у
`Task` нет поля `cache`, у `Answer` — свойства `cache_hit`.
"""

from __future__ import annotations

import dataclasses
import json

import platformdirs
import pytest
from conftest import GATEWAY_ROUTING, FakeGateway, json_reply
from typer.testing import CliRunner

from llmkit import Answer, LlmKit, Task
from llmkit.cli import runtime
from llmkit.cli.main import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def user_dirs(tmp_path, monkeypatch):
    """Каталоги пользователя — во временном: любой записанный файл виден тесту."""
    for name in ("user_data_dir", "user_cache_dir", "user_config_dir"):
        monkeypatch.setattr(
            platformdirs, name, lambda appname=None, *_a, _n=name, **_k: str(tmp_path / _n / str(appname))
        )
    return tmp_path


@pytest.fixture
def routing_file(tmp_path, monkeypatch):
    path = tmp_path / "routing.json"
    path.write_text(json.dumps(GATEWAY_ROUTING), encoding="utf-8")
    monkeypatch.setenv("LLMKIT_ROUTING_FILE", str(path))
    return path


@pytest.fixture
def fake_kit(monkeypatch):
    """Ответ шлюза без сети: httpx-транспорт фейка."""
    fake = FakeGateway(json_reply("ответ шлюза", provider="deepseek", cost=0.0001))

    def build(**kwargs):
        kwargs.setdefault("routing", GATEWAY_ROUTING)
        return LlmKit(transport=fake.transport, **kwargs)

    monkeypatch.setattr(runtime, "build_kit", build)
    monkeypatch.setenv("NINEROUTER_API_KEY", "ключ-шлюза")
    return fake


def test_completed_ask_leaves_no_row_and_no_file(routing_file, fake_kit, tmp_path):
    result = runner.invoke(app, ["ask", "вопрос", "--json"])
    assert result.exit_code == 0, result.output
    body = json.loads(result.stdout)
    assert body["ok"] is True and body["text"] == "ответ шлюза"
    assert "cache_hit" not in body
    # Ни журнала, ни кэша: после вызова в каталогах пользователя нет ни одного файла.
    written = [path for path in tmp_path.rglob("*") if path.is_file() and path.name != routing_file.name]
    assert written == []


@pytest.mark.usefixtures("routing_file", "fake_kit")
def test_database_url_is_not_read(monkeypatch):
    # Своей базы больше нет: строка подключения ни на что не влияет и не ломает вызов.
    monkeypatch.setenv("LLMKIT_DATABASE_URL", "postgresql+psycopg://нет-никакой-базы/llmkit")
    result = runner.invoke(app, ["ask", "вопрос", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["ok"] is True


@pytest.mark.usefixtures("routing_file", "fake_kit")
def test_no_cache_flag():
    result = runner.invoke(app, ["ask", "вопрос", "--no-cache", "--json"])
    assert result.exit_code == 2


def test_answer_and_task_have_no_cache_fields():
    assert "cache_hit" not in {field.name for field in dataclasses.fields(Answer)}
    assert "cache" not in {field.name for field in dataclasses.fields(Task)}
