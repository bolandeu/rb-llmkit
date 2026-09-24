"""Отображение провайдера и модели на аргументы LiteLLM (таблица раздела 3)."""

from __future__ import annotations

import pytest

from llmkit import config as config_mod
from llmkit import providers
from llmkit.config import Config
from llmkit.errors import ConfigError, KeyMissing

CONFIG = Config.model_validate(
    {
        "providers": {
            "openrouter": {"kind": "openrouter"},
            "openai": {"kind": "openai"},
            "anthropic": {"kind": "anthropic"},
            "gemini": {"kind": "gemini"},
            "ollama": {"kind": "ollama", "base_url": "https://ollama.com"},
            "local": {"kind": "ollama", "base_url": "http://localhost:11434", "requires_key": False},
            "ccode": config_mod.DEFAULTS["providers"]["ccode"],
            "deepseek": {
                "kind": "openai_compatible",
                "base_url": "https://api.deepseek.com/v1",
                "api_key_env": "DEEPSEEK_API_KEY",
            },
        },
        "levels": {},
    }
)

ENV = {
    "OPENROUTER_API_KEY": "k-or",
    "OPENAI_API_KEY": "k-oa",
    "ANTHROPIC_API_KEY": "k-an",
    "GEMINI_API_KEY": "k-ge",
    "OLLAMA_API_KEY": "k-ol",
    "DEEPSEEK_API_KEY": "k-ds",
    "CCODE_API_KEY": "k-cc",
}

CASES = [
    ("openrouter/openai/gpt-4o-mini", "openrouter/openai/gpt-4o-mini", None, "k-or", "TOOLS"),
    ("ccode/claude-sonnet-4-5", "openai/claude-sonnet-4-5", "https://all-api.ccode.dev/v1", "k-cc", "TOOLS"),
    ("openai/gpt-4o", "gpt-4o", None, "k-oa", "TOOLS"),
    ("anthropic/claude-sonnet-4", "anthropic/claude-sonnet-4", None, "k-an", "TOOLS"),
    ("gemini/gemini-2.0-flash", "gemini/gemini-2.0-flash", None, "k-ge", "TOOLS"),
    ("ollama/gpt-oss:120b", "ollama_chat/gpt-oss:120b", "https://ollama.com", "k-ol", "JSON"),
    ("deepseek/deepseek-chat", "openai/deepseek-chat", "https://api.deepseek.com/v1", "k-ds", "JSON"),
]


@pytest.mark.parametrize(("ref", "litellm_model", "api_base", "api_key", "mode"), CASES)
def test_build_maps_provider_to_litellm(ref, litellm_model, api_base, api_key, mode):
    call = providers.build(ref, CONFIG, env=ENV)
    assert call.litellm_model == litellm_model
    assert call.params.get("api_base") == api_base
    assert call.params.get("api_key") == api_key
    assert call.mode == mode
    assert providers.api_base(ref, CONFIG) == api_base


def test_api_key_is_not_in_repr():
    call = providers.build("openrouter/openai/gpt-4o-mini", CONFIG, env=ENV)
    assert "k-or" not in repr(call)


def test_provider_without_key_requirement():
    call = providers.build("local/llama3", CONFIG, env={})
    assert call.params == {"api_base": "http://localhost:11434"}


def test_missing_key_raises():
    with pytest.raises(KeyMissing):
        providers.build("openai/gpt-4o", CONFIG, env={})


def test_mode_can_be_overridden_by_config():
    config = Config.model_validate(
        {"providers": {"x": {"kind": "ollama", "base_url": "http://x", "mode": "tools"}}, "levels": {}}
    )
    assert providers.build("x/m", config, env={"OLLAMA_API_KEY": "k"}).mode == "TOOLS"


def test_bad_reference_and_unknown_kind():
    with pytest.raises(ConfigError):
        providers.split_ref("простотекст")
    config = Config.model_validate({"providers": {"x": {"kind": "неизвестно"}}, "levels": {}})
    with pytest.raises(ConfigError):
        providers.build("x/m", config, env={})


def test_openai_compatible_without_base_url():
    config = Config.model_validate({"providers": {"x": {"kind": "openai_compatible"}}, "levels": {}})
    with pytest.raises(ConfigError):
        providers.build("x/m", config, env={"X_API_KEY": "k"})


def test_price_from_config():
    config = Config.model_validate(
        {"providers": {"o": {"kind": "ollama", "base_url": "http://x", "prices": {"m": {"input": 1.0, "output": 2.0}}}},
         "levels": {}}
    )
    call = providers.build("o/m", config, env={"OLLAMA_API_KEY": "k"})
    assert providers.price_from_config(config, call, 1_000_000, 1_000_000) == pytest.approx(3.0)
    other = providers.build("o/другая", config, env={"OLLAMA_API_KEY": "k"})
    assert providers.price_from_config(config, other, 10, 10) is None
