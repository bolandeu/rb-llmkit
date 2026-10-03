"""Файл routing по умолчанию: `user_config_dir("llmkit")/routing.json`, когда нет --routing и LLMKIT_ROUTING_FILE.

Порядок: --routing → LLMKIT_ROUTING_FILE → файл по умолчанию → ROUTING_MISSING с путём по умолчанию.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import conftest as fakes
import platformdirs
import pytest
from conftest import ROUTING
from test_routing import OPENROUTER, anonymous
from typer.testing import CliRunner

from llmkit import LlmKit
from llmkit import keys as keys_mod
from llmkit.cli import runtime
from llmkit.cli.main import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def no_keychain(monkeypatch):
    monkeypatch.setattr(keys_mod, "from_keychain", lambda provider: None)


@pytest.fixture
def fake(monkeypatch):
    completion = fakes.FakeCompletion([anonymous("ответ модели")])
    monkeypatch.setattr(runtime, "build_kit", lambda **kwargs: LlmKit(completion=completion, **kwargs))
    return completion


def default_path() -> Path:
    return Path(platformdirs.user_config_dir("llmkit")) / "routing.json"


def write_default(data: dict, mode: int = 0o600) -> Path:
    path = default_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    os.chmod(path, mode)
    return path


def run(*args):
    return runner.invoke(app, list(args))


def test_default_path_is_routing_json_in_user_config_dir():
    assert runtime.default_routing_path() == default_path()


def test_default_file_is_used_without_argument_and_env(fake, monkeypatch):
    monkeypatch.setenv("LLM_OPENROUTER_API_KEY", "k")
    write_default(OPENROUTER)
    result = run("ask", "вопрос", "--json")
    assert result.exit_code == 0, result.output
    assert fake.models() == ["openrouter/a"]


def test_env_file_wins_over_default_file(fake, monkeypatch, tmp_path):
    write_default(OPENROUTER)
    path = tmp_path / "env-routing.json"
    path.write_text(json.dumps(ROUTING), encoding="utf-8")
    monkeypatch.setenv("LLMKIT_ROUTING_FILE", str(path))
    result = run("ask", "вопрос", "--json")
    assert result.exit_code == 0, result.output
    assert fake.models() == ["openai/m1"]


def test_argument_wins_over_default_file(fake):
    write_default(OPENROUTER)
    result = run("ask", "вопрос", "--routing", json.dumps(ROUTING), "--json")
    assert result.exit_code == 0, result.output
    assert fake.models() == ["openai/m1"]


def test_missing_everything_names_default_path(fake):
    result = run("ask", "вопрос", "--json")
    assert result.exit_code == 2
    error = json.loads(result.stdout)["error"]
    assert error["code"] == "ROUTING_MISSING"
    assert str(default_path()) in error["action"]
    assert "--routing" in error["action"] and "LLMKIT_ROUTING_FILE" in error["action"]


@pytest.mark.skipif(os.name != "posix", reason="права файла — POSIX")
def test_default_file_wider_than_600_warns_but_works(fake, monkeypatch):
    monkeypatch.setenv("LLM_OPENROUTER_API_KEY", "k")
    path = write_default(OPENROUTER, 0o644)
    result = run("ask", "вопрос", "--json")
    assert result.exit_code == 0, result.output
    assert str(path) in result.stderr and "600" in result.stderr
    assert fake.models() == ["openrouter/a"]


@pytest.mark.skipif(os.name != "posix", reason="права файла — POSIX")
def test_default_file_600_no_warning(fake, monkeypatch):
    monkeypatch.setenv("LLM_OPENROUTER_API_KEY", "k")
    path = write_default(OPENROUTER, 0o600)
    result = run("ask", "вопрос", "--json")
    assert result.exit_code == 0, result.output
    assert str(path) not in result.stderr


def test_auth_status_reads_default_file(monkeypatch):
    write_default({"providers": {"openrouter": {"protocol": "openrouter"}}})
    result = run("auth", "status", "--json")
    assert result.exit_code == 0, result.output
    providers = {item["provider"] for item in json.loads(result.stdout)["credentials"]}
    assert "openrouter" in providers


def test_config_path_shows_default_file():
    path = write_default(OPENROUTER)
    body = json.loads(run("config", "path", "--json").stdout)
    assert body["routing_file"] == str(path)


def test_describe_mentions_default_file():
    document = json.loads(run("describe", "--json").stdout)
    env = {item["name"]: item for item in document["x-rb-env"]}
    assert "routing.json" in env["LLMKIT_ROUTING_FILE"]["description"]
    config_dir = document["x-rb-data"]["user_config_dir"]
    assert config_dir["appname"] == "llmkit"
    assert [entry["path"] for entry in config_dir["files"]] == ["routing.json"]
