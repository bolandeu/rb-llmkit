"""CLI `llm`: конверты, коды выхода и работа поверх подменённого ядра."""

from __future__ import annotations

import importlib.metadata
import json
import re
import tomllib
from pathlib import Path

import httpx
import pytest
from conftest import ROUTING, FakeGateway, json_reply
from typer.testing import CliRunner

from llmkit import LlmKit
from llmkit import keys as keys_mod
from llmkit._distribution import DIST_NAME
from llmkit.cli import runtime
from llmkit.cli.main import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def no_keychain(monkeypatch):
    """Связку ключей ОС тесты не трогают."""
    monkeypatch.setattr(keys_mod, "from_keychain", lambda provider: None)


@pytest.fixture(autouse=True)
def routing_file(tmp_path, monkeypatch):
    """Routing из файла пользователя (LLMKIT_ROUTING_FILE), как у CLI на Mac."""
    path = tmp_path / "routing.json"
    path.write_text(json.dumps(ROUTING), encoding="utf-8")
    monkeypatch.setenv("LLMKIT_ROUTING_FILE", str(path))
    return path


@pytest.fixture
def fake_kit(monkeypatch):
    """Подменяет фабрику ядра: сеть — httpx-транспорт фейкового шлюза."""

    def install(*replies):
        fake = FakeGateway(*replies)

        def build(**kwargs):
            kwargs.setdefault("routing", ROUTING)
            return LlmKit(transport=fake.transport, **kwargs)

        monkeypatch.setattr(runtime, "build_kit", build)
        return fake

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
    assert result.exit_code == 0 and result.stdout.strip() == importlib.metadata.version("rb-llmkit")


def test_cost_on_empty_journal():
    result = run("cost", "--json")
    assert result.exit_code == 0
    body = payload(result)
    assert body["ok"] is True and body["rows"] == [] and body["total"]["calls"] == 0


def test_cost_rejects_bad_period():
    result = run("cost", "--since", "позавчера", "--json")
    assert result.exit_code == 2
    assert payload(result)["error"]["code"] == "INVALID_ARGUMENTS"


def test_config_path_lists_files():
    body = payload(run("config", "path", "--json"))
    assert body["ok"] is True and body["cache"] == body["usage"]  # кэш — в базе, не в файле cache.sqlite
    assert body["routing_file"].endswith("routing.json")


def test_config_path_reports_the_database_without_password(monkeypatch):
    monkeypatch.setenv("LLMKIT_DATABASE_URL", "postgresql+psycopg://user:s3cret@db.example:5432/llmkit")
    body = payload(run("config", "path", "--json"))
    assert body["cache"] == "postgresql+psycopg://user:***@db.example:5432/llmkit"
    assert "s3cret" not in json.dumps(body)


def test_config_init_is_removed():
    # config.toml больше не читается — шаблон для него не пишется.
    assert run("config", "init", "--json").exit_code == 2


def test_models_json_lists_providers_and_chain():
    body = payload(run("models", "--json"))
    # Только провайдеры routing: встроенных нет.
    providers = {row["provider"]: row for row in body["providers"]}
    assert set(providers) == {"a", "b"}
    assert providers["a"]["protocol"] == "openai_compatible"
    assert providers["a"]["base_url"] == "http://localhost:11111/v1"
    assert providers["a"]["has_key"] is True and providers["a"]["key_source"] == "env"
    assert body["chain"] == ["a/m1", "b/m2"]


def test_ask_json_envelope(fake_kit):
    fake_kit(json_reply("ответ модели", provider="deepseek", cost=0.0001))
    result = run("ask", "вопрос", "--tag", "tool=cli", "--json")
    assert result.exit_code == 0
    body = payload(result)
    assert body["ok"] is True and body["text"] == "ответ модели"
    assert body["model"] == "a/m1" and body["cache_hit"] is False
    assert body["tokens_in"] == 10 and body["cost_usd"] > 0
    # Вызов попал в журнал и виден в отчёте по метке.
    report = payload(run("cost", "--by", "tool", "--json"))
    assert report["rows"][0]["keys"] == {"tool": "cli"} and report["rows"][0]["calls"] == 1


def test_ask_human_output_is_text_only(fake_kit):
    fake_kit(json_reply("ответ модели"))
    result = run("ask", "вопрос")
    assert result.exit_code == 0 and result.stdout.strip() == "ответ модели"


def test_ask_reads_stdin(fake_kit):
    fake = fake_kit()
    result = run("ask", "--json", input="вопрос из stdin\n")
    assert result.exit_code == 0
    assert fake.bodies()[0]["messages"][-1]["content"] == "вопрос из stdin"


def test_ask_without_text_and_without_stdin_is_invalid(fake_kit):
    fake_kit()
    result = run("ask", "--json", input="")
    assert result.exit_code == 2
    assert payload(result)["error"]["code"] == "INVALID_ARGUMENTS"


def test_ask_rejects_bad_tag(fake_kit):
    fake_kit()
    result = run("ask", "вопрос", "--tag", "плохая-метка", "--json")
    assert result.exit_code == 2 and payload(result)["error"]["code"] == "INVALID_ARGUMENTS"


def test_ask_model_flag_sets_chain(fake_kit, routing_file):
    routing_file.write_text(json.dumps({"providers": ROUTING["providers"]}), encoding="utf-8")
    fake = fake_kit()
    assert run("ask", "вопрос", "--model", "b/m2", "--no-cache").exit_code == 0
    assert fake.models() == ["b/m2"]


def test_ask_no_retry_flag_disables_retries(fake_kit):
    fake = fake_kit(json_reply("  "))
    result = run("ask", "вопрос", "--no-retry", "--no-cache", "--json")
    assert result.exit_code == 5
    # Без --no-retry тот же пустой ответ повторяется retry.invalid_output раз.
    assert len(fake.requests) == 1


def test_ask_reports_missing_key(monkeypatch):
    monkeypatch.delenv("TEST_A_KEY")
    monkeypatch.delenv("TEST_B_KEY")
    result = run("ask", "вопрос", "--json")
    assert result.exit_code == 3  # нет ключа — код 3 по conventions.md
    error = payload(result)["error"]
    assert error["code"] == "AUTH_MISSING" and "llm keys set" in error["action"]
    assert error["variable"] == "TEST_A_KEY"


def test_json_command_prints_only_the_object(fake_kit, tmp_path):
    fake_kit(json_reply('{"x": 1}'))
    schema = tmp_path / "schema.json"
    schema.write_text(json.dumps({"type": "object", "properties": {"x": {"type": "integer"}}}), encoding="utf-8")
    result = run("json", "вопрос", "--schema", str(schema))
    assert result.exit_code == 0 and json.loads(result.stdout) == {"x": 1}
    enveloped = run("json", "вопрос", "--schema", str(schema), "--json")
    body = payload(enveloped)
    assert body["ok"] is True and body["data"] == {"x": 1} and body["cache_hit"] is True


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


def test_provider_failure_exit_code(fake_kit):
    fake_kit(httpx.Response(503, json={"error": "нет аккаунта"}))
    result = run("ask", "вопрос", "--json")
    assert result.exit_code == 5  # PROVIDER_ERROR по conventions.md
    assert payload(result)["error"]["code"] == "PROVIDER_ERROR"


def test_distribution_name_declared_once():
    """DIST_NAME задаёт только _distribution.py; повторное объявление при мерже молча победило бы."""
    src = Path(__file__).resolve().parents[1] / "src" / "llmkit"
    declaring = sorted(
        str(path.relative_to(src))
        for path in src.rglob("*.py")
        if re.search(r"^DIST_NAME\s*[:=]", path.read_text(), re.M)
    )
    assert declaring == ["_distribution.py"]


def test_distribution_name_matches_pyproject():
    pyproject = tomllib.loads((Path(__file__).resolve().parents[1] / "pyproject.toml").read_text())
    assert pyproject["project"]["name"] == DIST_NAME


def test_version_falls_back_to_legacy_distribution_name(monkeypatch):
    from llmkit import version

    installed = version.installed_version()
    monkeypatch.setattr(version, "DIST_NAME", "no-such-distribution-xyz")
    monkeypatch.setattr(version, "DIST_NAME_LEGACY", DIST_NAME)  # установка под старым именем
    assert version.installed_version() == installed
    monkeypatch.setattr(version, "DIST_NAME_LEGACY", None)
    assert version.installed_version() is None


def test_help_output_is_the_same_in_ci(same_in_ci) -> None:
    same_in_ci("test_help_documents_exit_codes or test_bare_call_prints_help_with_zero")


@pytest.mark.parametrize(
    "argv",
    [
        ["--json", "render", "--no-such-option"],
        ["render", "--json", "--no-such-option"],
        ["--json", "--no-such-option"],
    ],
)
def test_usage_error_under_json_is_the_envelope(argv):
    result = run(*argv)
    assert result.exit_code == 2
    body = payload(result)
    assert body["ok"] is False and body["error"]["code"] == "INVALID_ARGUMENTS" and body["error"]["message"]


def test_usage_error_without_json_stays_the_usage_message():
    result = run("render", "--no-such-option")
    assert result.exit_code == 2
    assert not result.stdout.lstrip().startswith("{")
    assert "No such option" in result.output


def test_usage_error_after_double_dash_json_is_not_a_flag():
    result = run("render", "--no-such-option", "--", "--json")
    assert result.exit_code == 2
    assert "No such option" in result.output
