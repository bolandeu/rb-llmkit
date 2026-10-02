"""CLI: `llm render` и `--template/--vars` у команд вызова модели (без сети)."""

from __future__ import annotations

import hashlib
import json
import sqlite3

import pytest
from conftest import ROUTING, FakeCompletion, response
from test_decide import DECIDE_ROUTING, QUESTIONS, FakeDecisions
from typer.testing import CliRunner

from llmkit import LlmKit
from llmkit import keys as keys_mod
from llmkit.cli import runtime
from llmkit.cli.main import app

runner = CliRunner()

SECRET = "секрет-клиента-42"


@pytest.fixture(autouse=True)
def no_keychain(monkeypatch):
    monkeypatch.setattr(keys_mod, "from_keychain", lambda provider: None)


@pytest.fixture(autouse=True)
def routing_file(tmp_path, monkeypatch):
    path = tmp_path / "routing.json"
    path.write_text(json.dumps(ROUTING), encoding="utf-8")
    monkeypatch.setenv("LLMKIT_ROUTING_FILE", str(path))


@pytest.fixture
def fake_kit(monkeypatch):
    def install(script=None):
        completion = FakeCompletion(script if script is not None else [response("ответ модели")])
        monkeypatch.setattr(runtime, "build_kit", lambda **kwargs: LlmKit(completion=completion, **kwargs))
        return completion

    return install


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
    completion = fake_kit()
    result = run("ask", "--template", str(template_file), "--vars", '{"name": "Мир"}', "--json")
    assert result.exit_code == 0, result.output
    assert completion.calls[0]["messages"][-1]["content"] == "Привет, Мир!"
    assert payload(result)["text"] == "ответ модели"


def test_ask_missing_variable_does_not_call_model(fake_kit, template_file):
    completion = fake_kit()
    result = run("ask", "--template", str(template_file), "--vars", "{}", "--json")
    assert result.exit_code == 2
    assert payload(result)["error"]["variable"] == "name"
    assert completion.calls == []


def test_ask_lenient(fake_kit, template_file):
    completion = fake_kit()
    result = run("ask", "--template", str(template_file), "--lenient", "--no-cache")
    assert result.exit_code == 0, result.output
    assert completion.calls[0]["messages"][-1]["content"] == "Привет, !"


def test_ask_template_and_text_together_is_exit_2(fake_kit, template_file):
    completion = fake_kit()
    result = run("ask", "вопрос", "--template", str(template_file), "--vars", '{"name": "x"}', "--json")
    assert result.exit_code == 2 and payload(result)["error"]["code"] == "INVALID_ARGUMENTS"
    assert completion.calls == []


def test_ask_vars_without_template_is_exit_2(fake_kit):
    fake_kit()
    result = run("ask", "вопрос", "--vars", '{"name": "x"}', "--json")
    assert result.exit_code == 2 and payload(result)["error"]["code"] == "INVALID_ARGUMENTS"


def _usage_dump(tmp_path) -> str:
    with sqlite3.connect(tmp_path / "usage.sqlite") as connection:
        rows = connection.execute("SELECT * FROM llmkit_calls").fetchall()
    assert rows
    return json.dumps(rows, ensure_ascii=False)


def test_ask_usage_has_template_name_and_hash_not_values(fake_kit, template_file, tmp_path):
    fake_kit()
    result = run(
        "ask", "--template", str(template_file), "--vars", json.dumps({"name": SECRET}), "--tag", "tool=t", "--json"
    )
    assert result.exit_code == 0, result.output
    digest = hashlib.sha256(template_file.read_bytes()).hexdigest()[:12]
    with sqlite3.connect(tmp_path / "usage.sqlite") as connection:
        (tags,) = connection.execute("SELECT tags FROM llmkit_calls").fetchone()
    assert json.loads(tags) == {"tool": "t", "template": "greet.md", "template_sha256": digest}
    assert SECRET not in _usage_dump(tmp_path)


def test_ask_inline_template_is_named_inline(fake_kit, tmp_path):
    fake_kit()
    template = "Привет, {{name}}!"
    result = run("ask", "--template", template, "--vars", json.dumps({"name": SECRET}), "--json")
    assert result.exit_code == 0, result.output
    with sqlite3.connect(tmp_path / "usage.sqlite") as connection:
        (tags,) = connection.execute("SELECT tags FROM llmkit_calls").fetchone()
    assert json.loads(tags) == {
        "template": "inline",
        "template_sha256": hashlib.sha256(template.encode()).hexdigest()[:12],
    }
    assert SECRET not in _usage_dump(tmp_path)


def test_json_command_renders_template(fake_kit, template_file, tmp_path):
    completion = fake_kit([response('{"x": 1}')])
    schema = tmp_path / "schema.json"
    schema.write_text(json.dumps({"type": "object", "properties": {"x": {"type": "integer"}}}), encoding="utf-8")
    result = run("json", "--schema", str(schema), "--template", str(template_file), "--vars", '{"name": "Мир"}')
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {"x": 1}
    assert completion.calls[0]["messages"][-1]["content"] == "Привет, Мир!"


def test_decide_renders_template(monkeypatch, template_file, tmp_path):
    monkeypatch.setenv("LLM_OPENROUTER_API_KEY", "ключ-or")
    fake = FakeDecisions()
    monkeypatch.setattr(runtime, "build_kit", lambda **kwargs: LlmKit(decisions=fake, **kwargs))
    questions = tmp_path / "q.json"
    questions.write_text(json.dumps(QUESTIONS), encoding="utf-8")
    result = run(
        "decide",
        "--questions",
        str(questions),
        "--template",
        str(template_file),
        "--vars",
        '{"name": "Мир"}',
        "--routing",
        json.dumps(DECIDE_ROUTING),
        "--json",
    )
    assert result.exit_code == 0, result.output
    assert fake.calls[0]["state"] == "Привет, Мир!"
