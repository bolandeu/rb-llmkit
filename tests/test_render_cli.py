"""CLI: `llm render` и `--template/--vars` у команд вызова модели (без сети)."""

from __future__ import annotations

import json

import pytest
from conftest import GATEWAY_ROUTING, FakeGateway, json_reply
from typer.testing import CliRunner

from llmkit import LlmKit
from llmkit.cli import runtime
from llmkit.cli.main import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def routing_file(tmp_path, monkeypatch):
    path = tmp_path / "routing.json"
    path.write_text(json.dumps(GATEWAY_ROUTING), encoding="utf-8")
    monkeypatch.setenv("LLMKIT_ROUTING_FILE", str(path))


@pytest.fixture
def fake_kit(monkeypatch):
    """Подменяет фабрику ядра: сеть — httpx-транспорт фейкового шлюза."""
    gateway = FakeGateway(json_reply("ответ модели"))
    monkeypatch.setattr(runtime, "build_kit", lambda **kwargs: LlmKit(transport=gateway.transport, **kwargs))
    monkeypatch.setenv("NINEROUTER_API_KEY", "ключ-шлюза")
    return gateway


def run(*args, **kwargs):
    return runner.invoke(app, list(args), **kwargs)


def payload(result) -> dict:
    return json.loads(result.stdout)


@pytest.fixture
def template_file(tmp_path):
    path = tmp_path / "greet.md"
    path.write_text("Привет, {{name}}!\n", encoding="utf-8")
    return path


# --- llm render ---------------------------------------------------------------


def test_render_template_from_file(template_file):
    result = run("render", "--template", str(template_file), "--vars", '{"name": "Мир"}')
    assert result.exit_code == 0, result.output
    assert result.stdout == "Привет, Мир!\n"


def test_render_template_from_string():
    result = run("render", "--template", "Привет, {{name}}!", "--vars", '{"name": "Мир"}')
    assert result.exit_code == 0, result.output
    assert result.stdout == "Привет, Мир!"


def test_render_template_from_stdin():
    result = run("render", "--template", "-", "--vars", '{"name": "Мир"}', input="Привет, {{name}}!\n")
    assert result.exit_code == 0, result.output
    assert result.stdout == "Привет, Мир!\n"


def test_render_vars_from_file(template_file, tmp_path):
    variables = tmp_path / "vars.json"
    variables.write_text('{"name": "<Мир & Co>"}', encoding="utf-8")
    result = run("render", "--template", str(template_file), "--vars", str(variables))
    assert result.exit_code == 0, result.output
    assert result.stdout == "Привет, <Мир & Co>!\n"  # без экранирования HTML


def test_render_without_vars_means_empty_object():
    result = run("render", "--template", "без переменных")
    assert result.exit_code == 0 and result.stdout == "без переменных"


def test_render_json_envelope(template_file):
    result = run("render", "--template", str(template_file), "--vars", '{"name": "Мир"}', "--json")
    assert result.exit_code == 0
    assert payload(result) == {"ok": True, "text": "Привет, Мир!\n"}


def test_render_missing_variable_is_exit_2_with_name(template_file):
    result = run("render", "--template", str(template_file), "--vars", "{}", "--json")
    assert result.exit_code == 2
    error = payload(result)["error"]
    assert error["code"] == "TEMPLATE_VARIABLE_MISSING"
    assert error["variable"] == "name" and "name" in error["message"]


def test_render_missing_variable_human_message(template_file):
    result = run("render", "--template", str(template_file))
    assert result.exit_code == 2
    assert "name" in result.stderr and result.stdout == ""


def test_render_lenient_renders_missing_as_empty(template_file):
    result = run("render", "--template", str(template_file), "--lenient")
    assert result.exit_code == 0 and result.stdout == "Привет, !\n"


@pytest.mark.parametrize("variables", ["{не json", "[1, 2]", '"строка"'])
def test_render_bad_vars_string_is_exit_2(template_file, variables):
    result = run("render", "--template", str(template_file), "--vars", variables, "--json")
    assert result.exit_code == 2
    assert payload(result)["error"]["code"] == "INVALID_ARGUMENTS"


def test_render_bad_vars_file_is_exit_2(template_file, tmp_path):
    broken = tmp_path / "vars.json"
    broken.write_text("{не json", encoding="utf-8")
    result = run("render", "--template", str(template_file), "--vars", str(broken), "--json")
    assert result.exit_code == 2 and payload(result)["error"]["code"] == "INVALID_ARGUMENTS"


def test_render_without_template_is_exit_2():
    result = run("render", "--vars", "{}", "--json")
    assert result.exit_code == 2
    assert payload(result)["error"]["code"] == "INVALID_ARGUMENTS"


def test_render_missing_template_file_is_exit_2(tmp_path):
    # Похоже на путь к файлу, а файла нет: не отправлять сам путь как текст промпта.
    result = run("render", "--template", str(tmp_path / "nope.md"), "--json")
    assert result.exit_code == 2 and payload(result)["error"]["code"] == "INVALID_ARGUMENTS"


def test_render_broken_template_is_exit_2():
    result = run("render", "--template", "{{#a}} без закрытия", "--vars", '{"a": true}', "--json")
    assert result.exit_code == 2 and payload(result)["error"]["code"] == "INVALID_ARGUMENTS"


# --- --template у команд вызова модели ---------------------------------------


def test_ask_renders_template_before_request(fake_kit, template_file):
    result = run("ask", "--template", str(template_file), "--vars", '{"name": "Мир"}', "--json")
    assert result.exit_code == 0, result.output
    assert fake_kit.bodies()[0]["messages"][-1]["content"] == "Привет, Мир!"
    assert payload(result)["text"] == "ответ модели"


def test_ask_missing_variable_does_not_call_model(fake_kit, template_file):
    result = run("ask", "--template", str(template_file), "--vars", "{}", "--json")
    assert result.exit_code == 2
    assert payload(result)["error"]["variable"] == "name"
    assert fake_kit.requests == []


def test_ask_lenient(fake_kit, template_file):
    result = run("ask", "--template", str(template_file), "--lenient")
    assert result.exit_code == 0, result.output
    assert fake_kit.bodies()[0]["messages"][-1]["content"] == "Привет, !"


def test_ask_template_and_text_together_is_exit_2(fake_kit, template_file):
    result = run("ask", "вопрос", "--template", str(template_file), "--vars", '{"name": "x"}', "--json")
    assert result.exit_code == 2 and payload(result)["error"]["code"] == "INVALID_ARGUMENTS"
    assert fake_kit.requests == []


def test_ask_vars_without_template_is_exit_2(fake_kit):
    result = run("ask", "вопрос", "--vars", '{"name": "x"}', "--json")
    assert result.exit_code == 2 and payload(result)["error"]["code"] == "INVALID_ARGUMENTS"


def test_json_command_renders_template(fake_kit, template_file, tmp_path, monkeypatch):
    gateway = FakeGateway(json_reply('{"x": 1}'))
    monkeypatch.setattr(runtime, "build_kit", lambda **kwargs: LlmKit(transport=gateway.transport, **kwargs))
    schema = tmp_path / "schema.json"
    schema.write_text(json.dumps({"type": "object", "properties": {"x": {"type": "integer"}}}), encoding="utf-8")
    result = run("json", "--schema", str(schema), "--template", str(template_file), "--vars", '{"name": "Мир"}')
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {"x": 1}
    assert gateway.bodies()[0]["messages"][-1]["content"] == "Привет, Мир!"
    assert fake_kit  # фикстура уже поставила ключ шлюза в окружение
