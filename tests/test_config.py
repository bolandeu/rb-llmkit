"""Настройки вызовов: дефолты в коде → env `LLMKIT_*` → аргументы `LlmKit(...)`.

С 0.8.0 файлов конфига нет: провайдеры и цепочка приходят данными (routing v1).
"""

from __future__ import annotations

import json

import pytest

from llmkit import config as config_mod
from llmkit.errors import ConfigError


def test_env_overrides_defaults():
    config = config_mod.load(env={"LLMKIT_CACHE": "0", "LLMKIT_LOG_LEVEL": "debug"})
    assert config.cache.enabled is False
    assert config.log_level == "DEBUG"


def test_kit_arguments_win_over_env():
    config = config_mod.load(overrides={"defaults": {"temperature": 0.9}, "cache": {"enabled": True}}, env={})
    assert config.defaults.temperature == 0.9


def test_config_files_are_not_read(tmp_path, monkeypatch):
    old = tmp_path / "config.toml"
    old.write_text("[defaults]\ntemperature = 0.7\n", encoding="utf-8")
    config = config_mod.load(env={"LLMKIT_CONFIG": str(old)})
    assert config.defaults.temperature == 0.0
    assert not hasattr(config, "providers") and not hasattr(config, "levels")


def test_no_providers_or_levels_in_code_defaults():
    assert "providers" not in config_mod.DEFAULTS and "levels" not in config_mod.DEFAULTS
    assert not hasattr(config_mod.Defaults(), "level")


def test_default_paths_use_platformdirs(monkeypatch):
    monkeypatch.setattr(config_mod, "DEFAULTS", {})
    config = config_mod.load(env={})
    assert config.cache_path().name == "cache.sqlite"
    assert config.usage_path().name == "usage.sqlite"
    assert "llmkit" in str(config.cache_path()).lower()


def test_ttl_days_must_be_at_least_one():
    with pytest.raises(ConfigError):
        config_mod.load(overrides={"cache": {"ttl_days": 0}}, env={})


def test_unknown_setting_is_an_error():
    with pytest.raises(ConfigError):
        config_mod.load(overrides={"defaults": {"levle": 1}}, env={})


def test_empty_llmkit_cache_is_ignored():
    assert config_mod.load(env={"LLMKIT_CACHE": ""}).cache.enabled is True
    assert config_mod.load(env={"LLMKIT_CACHE": "0"}).cache.enabled is False


def test_defaults_are_not_mutated_between_loads():
    first = config_mod.load(overrides={"defaults": {"max_tokens": 7}}, env={})
    second = config_mod.load(env={})
    assert first.defaults.max_tokens == 7
    assert second.defaults.max_tokens == config_mod.DEFAULTS["defaults"]["max_tokens"]


def test_default_daily_budget(monkeypatch):
    monkeypatch.setattr(config_mod, "DEFAULTS", {})
    assert config_mod.load(env={}).budget.daily_usd == 20.0


def test_bad_budget_tag_and_log_level():
    with pytest.raises(ConfigError):
        config_mod.load(overrides={"budget": {"tags": {"плохая метка": 1.0}}}, env={})
    with pytest.raises(ConfigError):
        config_mod.load(env={"LLMKIT_LOG_LEVEL": "ОЧЕНЬ_ПОДРОБНО"})


# Дефолты кода в момент импорта — до подмены в conftest (`isolated`).
CODE_DEFAULTS = config_mod.DEFAULTS


def test_code_defaults_are_former_mac_config_values(monkeypatch):
    """T86/0.8.1: значения config.toml с Mac стали дефолтами кода (решение tools и dev 2026-10-02)."""
    monkeypatch.setattr(config_mod, "DEFAULTS", CODE_DEFAULTS)
    config = config_mod.load(env={})
    assert config.defaults.max_tokens == 16000
    assert (config.retry.timeout, config.retry.rate_limit, config.retry.server, config.retry.invalid_output) == (
        0,
        6,
        6,
        2,
    )
    assert config.cache.ttl_days == 30 and config.budget.daily_usd == 20.0
    assert config.defaults.temperature == 0.0 and config.defaults.timeout == 120.0


def test_model_defaults_match_code_defaults(monkeypatch):
    """Без DEFAULTS (LlmKit(config=Config())) значения те же."""
    config = config_mod.Config()
    assert config.defaults.max_tokens == 16000
    assert (config.retry.timeout, config.retry.rate_limit, config.retry.server) == (0, 6, 6)


def test_config_show_reports_cache_in_the_local_default_database():
    from typer.testing import CliRunner

    from llmkit.cli.main import app

    result = CliRunner().invoke(app, ["config", "show", "--json"])
    assert result.exit_code == 0, result.output
    body = json.loads(result.stdout)
    assert body["cache"] == str(config_mod.load().usage_path())
    assert not body["cache"].endswith("cache.sqlite")
