"""Файл routing по умолчанию: `user_config_dir("llmkit")/routing.json`, когда нет --routing и LLMKIT_ROUTING_FILE.

Порядок: --routing → LLMKIT_ROUTING_FILE → файл по умолчанию → ROUTING_MISSING с путём по умолчанию.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import platformdirs
import pytest
from conftest import GATEWAY_ROUTING, FakeGateway, json_reply
from typer.testing import CliRunner

from rb_llmkit import LlmKit
from rb_llmkit.cli import runtime
from rb_llmkit.cli.main import app

runner = CliRunner()

# Routing без цепочки: модель приходит из `-m`, файл — только провайдеры.
PROVIDERS = {"providers": GATEWAY_ROUTING["providers"]}


@pytest.fixture
def fake(monkeypatch):
    gateway = FakeGateway(json_reply("ответ модели"))
    monkeypatch.setattr(runtime, "build_kit", lambda **kwargs: LlmKit(transport=gateway.transport, **kwargs))
    monkeypatch.setenv("NINEROUTER_API_KEY", "ключ-шлюза")
    return gateway


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


def test_default_file_is_used_without_argument_and_env(fake):
    write_default(PROVIDERS)
    result = run("ask", "вопрос", "-m", "Deep Sec", "--json")
    assert result.exit_code == 0, result.output
    assert fake.models() == ["Deep Sec"]


def test_env_file_wins_over_default_file(fake, tmp_path, monkeypatch):
    write_default(PROVIDERS)
    path = tmp_path / "env-routing.json"
    path.write_text(json.dumps(GATEWAY_ROUTING), encoding="utf-8")
    monkeypatch.setenv("LLMKIT_ROUTING_FILE", str(path))
    result = run("ask", "вопрос", "--json")
    assert result.exit_code == 0, result.output
    assert fake.models() == ["Deep Sec"]


def test_argument_wins_over_default_file(fake):
    write_default(PROVIDERS)
    result = run("ask", "вопрос", "--routing", json.dumps(GATEWAY_ROUTING), "--json")
    assert result.exit_code == 0, result.output
    assert fake.models() == ["Deep Sec"]


def test_missing_everything_names_default_path():
    result = run("ask", "вопрос", "--json")
    assert result.exit_code == 2
    error = json.loads(result.stdout)["error"]
    assert error["code"] == "ROUTING_MISSING"
    assert str(default_path()) in error["action"]
    assert "--routing" in error["action"] and "LLMKIT_ROUTING_FILE" in error["action"]


@pytest.mark.skipif(os.name != "posix", reason="права файла — POSIX")
def test_default_file_wider_than_600_warns_but_works(fake):
    assert fake  # сеть подменена
    path = write_default(PROVIDERS, 0o644)
    result = run("ask", "вопрос", "-m", "Deep Sec", "--json")
    assert result.exit_code == 0, result.output
    assert str(path) in result.stderr and "600" in result.stderr
    assert fake.models() == ["Deep Sec"]


@pytest.mark.skipif(os.name != "posix", reason="права файла — POSIX")
@pytest.mark.usefixtures("fake")
def test_default_file_600_no_warning():
    path = write_default(PROVIDERS, 0o600)
    result = run("ask", "вопрос", "-m", "Deep Sec", "--json")
    assert result.exit_code == 0, result.output
    assert str(path) not in result.stderr


@pytest.mark.usefixtures("fake")
def test_auth_status_reads_default_file():
    write_default(PROVIDERS)
    result = run("auth", "status", "--json")
    assert result.exit_code == 0, result.output
    providers = {item["provider"] for item in json.loads(result.stdout)["credentials"]}
    assert providers == {"9router"}


def test_describe_mentions_default_file():
    document = json.loads(run("describe", "--json").stdout)
    meta = {item["name"]: item["value"] for item in document["command"]["metadata"]}
    env = {item["name"]: item for item in meta["x-rb-env"]}
    assert "routing.json" in env["LLMKIT_ROUTING_FILE"]["description"]
    config_dir = meta["x-rb-data"]["user_config_dir"]
    assert config_dir["appname"] == "llmkit"
    assert [entry["path"] for entry in config_dir["files"]] == ["routing.json"]
