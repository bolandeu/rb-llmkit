"""Ключ шлюза: llmkit знает только имя переменной из routing и не читает связку ключей.

Своего хранилища у llmkit нет: ключ приходит из окружения, имя — `key_env`
провайдера routing. Ошибка отсутствующего ключа называет переменную, код
выхода — прежний, 3.
"""

from __future__ import annotations

import json

import pytest
from conftest import GATEWAY_ROUTING
from typer.testing import CliRunner

from rb_llmkit import keys
from rb_llmkit.cli.main import app

runner = CliRunner()
VARIABLE = "NINEROUTER_API_KEY"


@pytest.fixture(autouse=True)
def routing_file(tmp_path, monkeypatch):
    """Провайдеры — из routing пользователя, как у CLI на Mac."""
    path = tmp_path / "routing.json"
    path.write_text(json.dumps(GATEWAY_ROUTING), encoding="utf-8")
    monkeypatch.setenv("LLMKIT_ROUTING_FILE", str(path))
    return path


@pytest.fixture(autouse=True)
def no_key_env(monkeypatch):
    """Ключа шлюза в окружении нет: фикстура `isolated` уже убрала *_API_KEY."""
    monkeypatch.delenv(VARIABLE, raising=False)


def ask(*extra: str):
    result = runner.invoke(app, ["ask", "вопрос", *extra, "--json"])
    return result, json.loads(result.stdout)


def assert_missing_key(result, body) -> None:
    assert result.exit_code == 3, result.output
    error = body["error"]
    assert error["code"] == "AUTH_MISSING" and error["variable"] == VARIABLE
    assert VARIABLE in error["message"] + error.get("action", "")


def test_missing_gateway_key_names_the_variable():
    result, body = ask()
    assert_missing_key(result, body)


def test_keychain_is_not_a_key_source(monkeypatch):
    # Связки ключей у llmkit больше нет: значение оттуда не спасает от ошибки.
    monkeypatch.setattr(keys, "from_keychain", lambda _provider: "ключ-из-связки", raising=False)
    result, body = ask()
    assert_missing_key(result, body)


def test_keys_set_is_gone():
    # Класть ключ в связку ключей ОС больше некуда и незачем.
    result = runner.invoke(app, ["keys", "set", "9router", "--stdin", "--json"], input="секрет\n")
    assert result.exit_code == 2
