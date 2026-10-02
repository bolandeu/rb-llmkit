"""Провайдер из routing и модель → аргументы LiteLLM (таблица раздела 3)."""

from __future__ import annotations

import pytest

from llmkit import providers
from llmkit import routing as routing_mod
from llmkit.errors import KeyMissing, RoutingInvalid

ROUTING = routing_mod.parse(
    {
        "providers": {
            "openrouter": {"protocol": "openrouter", "key_env": "LLM_OPENROUTER_API_KEY"},
            "openai": {"protocol": "openai", "key_env": "LLM_OPENAI_API_KEY"},
            "anthropic": {"protocol": "anthropic", "key_env": "LLM_ANTHROPIC_API_KEY"},
            "gemini": {"protocol": "gemini", "key_env": "LLM_GEMINI_API_KEY"},
            "ollama": {"protocol": "ollama", "base_url": "https://ollama.com", "key_env": "LLM_OLLAMA_API_KEY"},
            "ccode": {
                "protocol": "openai_compatible",
                "base_url": "https://all-api.ccode.dev/v1",
                "key_env": "LLM_CCODE_API_KEY",
                "mode": "TOOLS",
            },
            "anymodel": {
                "protocol": "openai_compatible",
                "base_url": "https://anymodel.org/v1",
                "key_env": "LLM_ANYMODEL_API_KEY",
                "mode": "TOOLS",
            },
            "deepseek": {
                "protocol": "openai_compatible",
                "base_url": "https://api.deepseek.com/v1",
                "key_env": "DEEPSEEK_API_KEY",
            },
        },
        "chain": ["openrouter/openai/gpt-4o-mini"],
        "prices": {"ollama/m": {"input": 1.0, "output": 2.0}},
    }
)

ENV = {
    "LLM_OPENROUTER_API_KEY": "k-or",
    "LLM_OPENAI_API_KEY": "k-oa",
    "LLM_ANTHROPIC_API_KEY": "k-an",
    "LLM_GEMINI_API_KEY": "k-ge",
    "LLM_OLLAMA_API_KEY": "k-ol",
    "DEEPSEEK_API_KEY": "k-ds",
    "LLM_CCODE_API_KEY": "k-cc",
    "LLM_ANYMODEL_API_KEY": "k-am",
}

CASES = [
    ("openrouter/openai/gpt-4o-mini", "openrouter/openai/gpt-4o-mini", None, "k-or", "TOOLS"),
    ("ccode/claude-sonnet-4-5", "openai/claude-sonnet-4-5", "https://all-api.ccode.dev/v1", "k-cc", "TOOLS"),
    ("anymodel/am/gpt-5.6-terra", "openai/am/gpt-5.6-terra", "https://anymodel.org/v1", "k-am", "TOOLS"),
    ("openai/gpt-4o", "gpt-4o", None, "k-oa", "TOOLS"),
    ("anthropic/claude-sonnet-4", "anthropic/claude-sonnet-4", None, "k-an", "TOOLS"),
    ("gemini/gemini-2.0-flash", "gemini/gemini-2.0-flash", None, "k-ge", "TOOLS"),
    ("ollama/gpt-oss:120b", "ollama_chat/gpt-oss:120b", "https://ollama.com", "k-ol", "JSON"),
    ("deepseek/deepseek-chat", "openai/deepseek-chat", "https://api.deepseek.com/v1", "k-ds", "JSON"),
]


@pytest.mark.parametrize(("ref", "litellm_model", "api_base", "api_key", "mode"), CASES)
def test_build_maps_provider_to_litellm(ref, litellm_model, api_base, api_key, mode):
    call = providers.build(ref, ROUTING, env=ENV)
    assert call.litellm_model == litellm_model
    assert call.params.get("api_base") == api_base
    assert call.params.get("api_key") == api_key
    assert call.mode == mode
    assert providers.api_base(ref, ROUTING) == api_base


def test_api_key_is_not_in_repr():
    call = providers.build("openrouter/openai/gpt-4o-mini", ROUTING, env=ENV)
    assert "k-or" not in repr(call)


def test_missing_key_raises_with_env_name():
    with pytest.raises(KeyMissing) as caught:
        providers.build("openai/gpt-4o", ROUTING, env={})
    assert caught.value.env_var == "LLM_OPENAI_API_KEY"


def test_bad_reference():
    with pytest.raises(RoutingInvalid):
        providers.split_ref("простотекст")


def test_openai_compatible_without_base_url_is_invalid_routing():
    with pytest.raises(RoutingInvalid) as caught:
        routing_mod.parse({"providers": {"x": {"protocol": "openai_compatible"}}, "chain": ["x/m"]})
    assert caught.value.path == "/providers/x/base_url"


def test_price_from_routing():
    call = providers.build("ollama/m", ROUTING, env=ENV)
    assert providers.price_from_routing(ROUTING, call, 1_000_000, 1_000_000) == pytest.approx(3.0)
    other = providers.build("ollama/другая", ROUTING, env=ENV)
    assert providers.price_from_routing(ROUTING, other, 10, 10) is None
