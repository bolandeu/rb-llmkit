"""Загрузка и слияние слоёв конфига."""

from __future__ import annotations

import pytest

from llmkit import config as config_mod
from llmkit.errors import ConfigError

USER = """
[defaults]
level = "judge"
temperature = 0.7
[levels]
judge = ["a/m1"]
[providers.a]
kind = "openai_compatible"
base_url = "http://user/v1"
"""

PROJECT = """
[defaults]
temperature = 0.1
[providers.a]
base_url = "http://project/v1"
"""


@pytest.fixture
def files(tmp_path, monkeypatch):
    """Пользовательский и проектный конфиги вместо реальных путей."""
    monkeypatch.delenv("LLMKIT_CONFIG", raising=False)
    user = tmp_path / "user.toml"
    user.write_text(USER, encoding="utf-8")
    monkeypatch.setattr(config_mod, "user_config_path", lambda: user)
    project_dir = tmp_path / "work" / ".llmkit"
    project_dir.mkdir(parents=True)
    (project_dir / "config.toml").write_text(PROJECT, encoding="utf-8")
    monkeypatch.chdir(tmp_path / "work")
    return user


def test_project_overrides_user_and_env_overrides_both(files):
    config = config_mod.load(env={"LLMKIT_CACHE": "0", "LLMKIT_LOG_LEVEL": "debug"})
    assert config.defaults.level == "judge"  # из пользовательского
    assert config.defaults.temperature == 0.1  # перекрыт проектным
    assert config.providers["a"].base_url == "http://project/v1"
    assert config.cache.enabled is False  # env
    assert config.log_level == "DEBUG"
    # Дефолты в коде остаются там, где их не трогали.
    assert config.providers["ollama"].base_url == "https://ollama.com"


def test_kit_arguments_win_over_files(files):
    config = config_mod.load(overrides={"defaults": {"temperature": 0.9}}, env={})
    assert config.defaults.temperature == 0.9


def test_llmkit_config_replaces_file_search(tmp_path, monkeypatch, files):
    explicit = tmp_path / "explicit.toml"
    explicit.write_text('[defaults]\nlevel = "strong"\n', encoding="utf-8")
    config = config_mod.load(env={"LLMKIT_CONFIG": str(explicit)})
    assert config.defaults.level == "strong"
    assert "a" not in config.providers  # пользовательский и проектный слои не читались


def test_missing_explicit_config_is_an_error(tmp_path):
    with pytest.raises(ConfigError):
        config_mod.load(env={"LLMKIT_CONFIG": str(tmp_path / "нет.toml")})


def test_broken_toml_and_unknown_field(tmp_path, monkeypatch):
    broken = tmp_path / "broken.toml"
    broken.write_text("[defaults\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        config_mod.load(env={"LLMKIT_CONFIG": str(broken)})
    unknown = tmp_path / "unknown.toml"
    unknown.write_text("[defaults]\nlevle = 1\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        config_mod.load(env={"LLMKIT_CONFIG": str(unknown)})


def test_unknown_level_and_provider(files):
    config = config_mod.load(env={})
    with pytest.raises(ConfigError):
        config.chain_for("нет-такого")
    with pytest.raises(ConfigError):
        config.provider("нет-такого")


def test_default_paths_use_platformdirs(files):
    config = config_mod.load(env={})
    assert config.cache_path().name == "cache.sqlite"
    assert config.usage_path().name == "usage.sqlite"
    assert "llmkit" in str(config.cache_path()).lower()
