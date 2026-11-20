"""Routing v1 эпохи шлюза: один провайдер openai_compatible, имена моделей как есть, без цен."""

from __future__ import annotations

import json

import pytest
from conftest import GATEWAY_ROUTING
from typer.testing import CliRunner

from rb_llmkit import RoutingInvalid
from rb_llmkit import routing as routing_mod
from rb_llmkit.cli.main import app

runner = CliRunner()

GATEWAY = {
    "providers": {
        "9router": {
            "protocol": "openai_compatible",
            "base_url": "http://localhost:20128/v1",
            "key_env": "NINEROUTER_API_KEY",
        }
    },
    "chain": ["Deep Sec", "opencode-go"],
}


def provider(**fields) -> dict:
    return {"providers": {"9router": fields}, "chain": ["Deep Sec"]}


def test_gateway_routing_is_parsed():
    parsed = routing_mod.parse(GATEWAY)
    found = parsed.provider("9router")
    assert found.protocol == "openai_compatible"
    assert found.base_url == "http://localhost:20128/v1"
    assert found.key_env == "NINEROUTER_API_KEY"
    assert parsed.chain == ["Deep Sec", "opencode-go"]


def test_model_names_are_kept_verbatim():
    """Комбо и имена с префиксом идут строкой как в настройке шлюза: разбора `провайдер/модель` нет."""
    chain = ["deepseek/deepseek-v4.1-flash-1017", "Deep Sec", "opencode-go/qwen3-coder"]
    assert routing_mod.parse({**GATEWAY, "chain": chain}).chain == chain


def test_chain_from_the_command_line_is_kept_verbatim():
    parsed = routing_mod.parse({"providers": GATEWAY["providers"], "chain": None}, require_chain=False)
    assert parsed.with_chain(["Deep Sec"]).chain == ["Deep Sec"]


def test_the_gateway_key_is_the_named_environment_variable():
    routing = provider(protocol="openai_compatible", base_url="http://localhost:20128/v1", key_env="GATEWAY_KEY")
    assert routing_mod.parse(routing).provider("9router").key_env == "GATEWAY_KEY"


INVALID = [
    (
        {"providers": {"9router": {"protocol": "openrouter", "key_env": "K"}}, "chain": ["m"]},
        "/providers/9router/protocol",
    ),
    (
        {
            **GATEWAY,
            "prices": {"Deep Sec": {"input": 1.0, "output": 2.0}},
        },
        "/prices",
    ),
    (provider(protocol="openai_compatible", key_env="K"), "/providers/9router/base_url"),
    (provider(protocol="openai_compatible", base_url="http://localhost:20128/v1"), "/providers/9router/key_env"),
    ({"providers": GATEWAY["providers"]}, "/chain"),
    ({"providers": GATEWAY["providers"], "chain": []}, "/chain"),
]


@pytest.mark.parametrize(("routing", "path"), INVALID)
def test_invalid_routing_names_the_field(routing, path):
    with pytest.raises(RoutingInvalid) as caught:
        routing_mod.parse(routing)
    assert caught.value.path == path


@pytest.mark.parametrize(("routing", "path"), INVALID[:2])
def test_cli_refuses_invalid_routing_with_the_field(routing, path):
    result = runner.invoke(app, ["ask", "вопрос", "--routing", json.dumps(routing), "--json"])
    assert result.exit_code == 2
    error = json.loads(result.stdout)["error"]
    assert error["code"] == "ROUTING_INVALID" and error["path"] == path


def test_gateway_routing_from_a_file_is_loaded(tmp_path, monkeypatch):
    spec = tmp_path / "routing.json"
    spec.write_text(json.dumps(GATEWAY_ROUTING), encoding="utf-8")
    monkeypatch.setenv("LLMKIT_ROUTING_FILE", str(spec))
    from rb_llmkit.cli import runtime

    assert runtime.load_routing(None).chain == ["Deep Sec", "opencode-go"]
