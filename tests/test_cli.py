"""CLI `llm`: конверты, коды выхода и работа поверх подменённого ядра."""

from __future__ import annotations

import importlib.metadata
import json

import conftest as fakes_module
import pytest
from conftest import FakeCompletion, response
from typer.testing import CliRunner

from llmkit import LlmKit
from llmkit import keys as keys_mod
from llmkit.cli import runtime
from llmkit.cli.main import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def no_keychain(monkeypatch):
    """Связку ключей ОС тесты не трогают."""
    monkeypatch.setattr(keys_mod, "from_keychain", lambda provider: None)


@pytest.fixture
def fake_kit(monkeypatch):
    """Подменяет фабрику ядра: вызовы модели не уходят в сеть."""

    def install(script=None):
        completion = FakeCompletion(script if script is not None else [response("ответ модели")])
        monkeypatch.setattr(runtime, "build_kit", lambda **kwargs: LlmKit(completion=completion, **kwargs))
        return completion

    return install


def run(*args, **kwargs):
    return runner.invoke(app, list(args), **kwargs)


def payload(result) -> dict:
    return json.loads(result.stdout)


def test_help_documents_exit_codes():
    result = run("--help")
    assert result.exit_code == 0
    assert "Коды выхода" in result.stdout and "--json" in result.stdout


def test_bare_call_prints_help_with_zero():
    result = run()
    assert result.exit_code == 0 and "Usage: llm" in result.stdout


def test_group_without_subcommand_prints_help():
    result = run("keys")
    assert result.exit_code == 0 and "status" in result.stdout


def test_version():
    result = run("--version")
    # Голая версия: её сверяет с версией колеса гейт scripts/release.py.
    assert result.exit_code == 0 and result.stdout.strip() == importlib.metadata.version("llmkit")


def test_cost_on_empty_journal():
    result = run("cost", "--json")
    assert result.exit_code == 0
    body = payload(result)
    assert body["ok"] is True and body["rows"] == [] and body["total"]["calls"] == 0


def test_cost_rejects_bad_period():
    result = run("cost", "--since", "позавчера", "--json")
    assert result.exit_code == 2
    assert payload(result)["error"]["code"] == "INVALID_ARGUMENTS"


def test_config_init_show_and_force(tmp_path, monkeypatch):
    target = tmp_path / "new" / "config.toml"
    monkeypatch.setenv("LLMKIT_CONFIG", str(target))
    created = run("config", "init", "--json")
    assert created.exit_code == 0 and target.is_file()
    assert payload(created)["path"] == str(target)
    again = run("config", "init", "--json")
    assert again.exit_code == 2 and payload(again)["error"]["code"] == "INVALID_ARGUMENTS"
    assert run("config", "init", "--force", "--json").exit_code == 0
    shown = run("config", "show", "--json")
    assert shown.exit_code == 0
    config = payload(shown)["config"]
    assert config["defaults"]["level"] == "cheap"
    assert "openrouter" in config["providers"]


def test_config_show_hides_api_key(tmp_path, monkeypatch):
    target = tmp_path / "secret.toml"
    target.write_text('[providers.x]\nkind = "openai"\napi_key = "секрет"\n', encoding="utf-8")
    monkeypatch.setenv("LLMKIT_CONFIG", str(target))
    result = run("config", "show", "--json")
    assert result.exit_code == 0
    assert payload(result)["config"]["providers"]["x"]["api_key"] == "***"
    assert "секрет" not in result.stdout


def test_config_path_lists_files():
    body = payload(run("config", "path", "--json"))
    assert body["ok"] is True and body["cache"].endswith("cache.sqlite")


def test_models_json_lists_providers_and_levels():
    body = payload(run("models", "--json"))
    # Провайдеры из тестового конфига плюс дефолтные из кода.
    providers = {row["provider"]: row for row in body["providers"]}
    assert providers["a"]["kind"] == "openai_compatible"
    assert providers["a"]["base_url"] == "http://localhost:11111/v1"
    assert providers["a"]["has_key"] is True and providers["a"]["key_source"] == "env"
    assert body["levels"]["cheap"] == ["a/m1", "b/m2"]
    assert body["default_level"] == "cheap"


def test_ask_json_envelope(fake_kit):
    fake_kit()
    result = run("ask", "вопрос", "--tag", "tool=cli", "--json")
    assert result.exit_code == 0
    body = payload(result)
    assert body["ok"] is True and body["data"] == "ответ модели"
    assert body["model"] == "a/m1" and body["source"] == "llm"
    assert body["prompt_tokens"] == 10 and body["cost_usd"] > 0
    # Вызов попал в журнал и виден в отчёте по метке.
    report = payload(run("cost", "--by", "tool", "--json"))
    assert report["rows"][0]["keys"] == {"tool": "cli"} and report["rows"][0]["calls"] == 1


def test_ask_human_output_is_text_only(fake_kit):
    fake_kit()
    result = run("ask", "вопрос")
    assert result.exit_code == 0 and result.stdout.strip() == "ответ модели"


def test_ask_reads_stdin(fake_kit):
    completion = fake_kit()
    result = run("ask", "--json", input="вопрос из stdin\n")
    assert result.exit_code == 0
    assert completion.calls[0]["messages"][-1]["content"] == "вопрос из stdin"


def test_ask_without_text_and_without_stdin_is_invalid(fake_kit):
    fake_kit()
    result = run("ask", "--json", input="")
    assert result.exit_code == 2
    assert payload(result)["error"]["code"] == "INVALID_ARGUMENTS"


def test_ask_rejects_bad_tag(fake_kit):
    fake_kit()
    result = run("ask", "вопрос", "--tag", "плохая-метка", "--json")
    assert result.exit_code == 2 and payload(result)["error"]["code"] == "INVALID_ARGUMENTS"


def test_ask_model_flag_overrides_level(fake_kit):
    completion = fake_kit()
    assert run("ask", "вопрос", "--model", "b/m2", "--no-cache").exit_code == 0
    assert completion.calls[0]["model"] == "openai/m2"


def test_ask_timeout_flag_overrides_default(fake_kit):
    completion = fake_kit()
    assert run("ask", "вопрос", "--timeout", "5", "--no-cache").exit_code == 0
    assert completion.calls[0]["timeout"] == 5.0


def test_ask_no_retry_flag_disables_retries(fake_kit):
    completion = fake_kit({"openai/m1": [fakes_module.RateLimitError("429")], "openai/m2": [response("вторая")]})
    result = run("ask", "вопрос", "--no-retry", "--no-cache")
    assert result.exit_code == 0
    # Без --no-retry было бы три попытки a/m1 (retry.rate_limit=2) перед фолбэком.
    assert completion.models() == ["openai/m1", "openai/m2"]


def test_ask_reports_missing_key(monkeypatch):
    monkeypatch.delenv("TEST_A_KEY")
    monkeypatch.delenv("TEST_B_KEY")
    result = run("ask", "вопрос", "--json")
    assert result.exit_code == 3  # AUTH_REQUIRED по conventions.md
    error = payload(result)["error"]
    assert error["code"] == "AUTH_REQUIRED" and "llm keys set" in error["action"]


def test_json_command_prints_only_the_object(fake_kit, tmp_path):
    fake_kit([response('{"x": 1}')])
    schema = tmp_path / "schema.json"
    schema.write_text(json.dumps({"type": "object", "properties": {"x": {"type": "integer"}}}), encoding="utf-8")
    result = run("json", "вопрос", "--schema", str(schema))
    assert result.exit_code == 0 and json.loads(result.stdout) == {"x": 1}
    enveloped = run("json", "вопрос", "--schema", str(schema), "--json")
    body = payload(enveloped)
    assert body["ok"] is True and body["data"] == {"x": 1} and body["source"] == "cache"


def test_json_command_rejects_broken_schema(fake_kit, tmp_path):
    fake_kit()
    broken = tmp_path / "broken.json"
    broken.write_text("{не json", encoding="utf-8")
    result = run("json", "вопрос", "--schema", str(broken), "--json")
    assert result.exit_code == 2 and payload(result)["error"]["code"] == "INVALID_ARGUMENTS"


def test_keys_status_without_and_with_env(monkeypatch):
    monkeypatch.delenv("TEST_A_KEY")
    monkeypatch.delenv("TEST_B_KEY")
    empty = {row["provider"]: row for row in payload(run("keys", "status", "--json"))["providers"]}
    assert empty["a"]["source"] == "none" and empty["b"]["source"] == "none"
    assert empty["a"]["env_var"] == "TEST_A_KEY"
    monkeypatch.setenv("TEST_A_KEY", "ключ")
    filled = payload(run("keys", "status", "--json"))
    assert {row["provider"]: row["source"] for row in filled["providers"]}["a"] == "env"
    assert "ключ" not in json.dumps(filled, ensure_ascii=False)


def test_keys_set_and_rm(monkeypatch):
    stored = {}
    monkeypatch.setattr(keys_mod, "store", lambda provider, secret: stored.update({provider: secret}))
    monkeypatch.setattr(keys_mod, "delete", lambda provider: stored.pop(provider, None))
    result = run("keys", "set", "a", "--stdin", "--json", input="секретный-ключ\n")
    assert result.exit_code == 0 and stored == {"a": "секретный-ключ"}
    assert "секретный-ключ" not in result.stdout
    assert run("keys", "rm", "a", "--json").exit_code == 0 and stored == {}


def test_keys_set_unknown_provider():
    result = run("keys", "set", "нет-такого", "--stdin", "--json", input="ключ\n")
    assert result.exit_code == 2 and payload(result)["error"]["code"] == "INVALID_ARGUMENTS"


def test_serve_is_not_implemented_yet():
    result = run("serve", "--json")
    assert result.exit_code == 2
    assert payload(result)["error"]["code"] == "NOT_IMPLEMENTED"


def test_models_explains_unknown_provider_in_level(tmp_path, monkeypatch):
    broken = tmp_path / "broken-levels.toml"
    broken.write_text('[levels]\ncheap = ["нет-такого/m1"]\n', encoding="utf-8")
    monkeypatch.setenv("LLMKIT_CONFIG", str(broken))
    result = run("models", "--json")
    assert result.exit_code == 2
    error = payload(result)["error"]
    assert error["code"] == "INVALID_ARGUMENTS" and "нет-такого" in error["message"]


def test_config_init_template_has_default_budget(tmp_path, monkeypatch):
    target = tmp_path / "шаблон.toml"
    monkeypatch.setenv("LLMKIT_CONFIG", str(target))
    assert run("config", "init", "--json").exit_code == 0
    body = target.read_text(encoding="utf-8")
    assert "daily_usd = 20.0" in body and "# [budget.tags]" in body
    # Шаблон должен читаться обратно без ошибок.
    assert run("config", "show", "--json").exit_code == 0


def test_provider_failure_exit_code(fake_kit):
    fake_kit([fakes_module.BadRequestError("нет")])
    result = run("ask", "вопрос", "--json")
    assert result.exit_code == 5  # PROVIDER_ERROR по conventions.md
    assert payload(result)["error"]["code"] == "PROVIDER_ERROR"
