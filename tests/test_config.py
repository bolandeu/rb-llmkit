"""Настройки вызовов: дефолты в коде → env `LLMKIT_*` → аргументы `LlmKit(...)`.

Файлов конфига нет: провайдеры и цепочка приходят данными (routing v1).
"""

from __future__ import annotations

import json

import pytest

from llmkit import config as config_mod
from llmkit.errors import ConfigError


def test_env_overrides_defaults():
    config = config_mod.load(env={"LLMKIT_LOG_LEVEL": "debug"})
    assert config.log_level == "DEBUG"


def test_kit_arguments_win_over_env():
    config = config_mod.load(overrides={"defaults": {"temperature": 0.9}}, env={})
    assert config.defaults.temperature == 0.9


def test_config_files_are_not_read(tmp_path):
    old = tmp_path / "config.toml"
    old.write_text("[defaults]\ntemperature = 0.7\n", encoding="utf-8")
    config = config_mod.load(env={"LLMKIT_CONFIG": str(old)})
    assert config.defaults.temperature == 0.0
    assert not hasattr(config, "providers") and not hasattr(config, "levels")


def test_no_providers_or_levels_in_code_defaults():
    assert "providers" not in config_mod.DEFAULTS and "levels" not in config_mod.DEFAULTS
    assert not hasattr(config_mod.Defaults(), "level")


def test_unknown_setting_is_an_error():
    with pytest.raises(ConfigError):
        config_mod.load(overrides={"defaults": {"levle": 1}}, env={})


def test_own_state_settings_are_gone():
    """Ни базы, ни кэша, ни бюджета: настройки только про сам вызов."""
    config = config_mod.Config()
    for gone in ("cache", "usage", "budget"):
        assert not hasattr(config, gone)


def test_defaults_are_not_mutated_between_loads():
    first = config_mod.load(overrides={"defaults": {"max_tokens": 7}}, env={})
    second = config_mod.load(env={})
    assert first.defaults.max_tokens == 7
    assert second.defaults.max_tokens == config_mod.DEFAULTS["defaults"]["max_tokens"]


def test_bad_log_level():
    with pytest.raises(ConfigError):
        config_mod.load(env={"LLMKIT_LOG_LEVEL": "ОЧЕНЬ_ПОДРОБНО"})


def test_code_defaults_are_former_mac_config_values():
    """T86/0.8.1: значения config.toml с Mac стали дефолтами кода (решение tools и dev 2026-10-02)."""
    config = config_mod.load(env={})
    assert config.defaults.max_tokens == 16000
    assert (config.retry.timeout, config.retry.rate_limit, config.retry.server, config.retry.invalid_output) == (
        0,
        6,
        6,
        2,
    )
    assert config.defaults.temperature == 0.0 and config.defaults.timeout == 120.0


def test_model_defaults_match_code_defaults():
    """Без env (LlmKit(config=Config())) значения те же."""
    config = config_mod.Config()
    assert config.defaults.max_tokens == 16000
    assert (config.retry.timeout, config.retry.rate_limit, config.retry.server) == (0, 6, 6)


def test_config_show_reports_the_settings():
    from typer.testing import CliRunner

    from llmkit.cli.main import app

    result = CliRunner().invoke(app, ["config", "show", "--json"])
    assert result.exit_code == 0, result.output
    body = json.loads(result.stdout)
    assert body["config"]["defaults"]["max_tokens"] == 16000
    assert "cache" not in body
