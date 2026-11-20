"""`llm routing import`: config.toml llmkit < 0.8 → routing v1 (без сети)."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from rb_llmkit import legacy
from rb_llmkit import routing as routing_mod
from rb_llmkit.cli.main import app

CONFIG = Path(__file__).parent / "data" / "legacy_config.toml"


def test_only_gateway_providers_are_carried_over():
    converted = legacy.convert(legacy.read(CONFIG))
    providers = converted["routing"]["providers"]
    # ccode и anymodel были openai_compatible с адресом — они и есть шлюзы;
    # openrouter, подписки chatgpt и claude, цены и режимы остаются у 9router.
    assert set(providers) == {"ccode", "anymodel"}
    assert providers["ccode"] == {
        "protocol": "openai_compatible",
        "base_url": "https://all-api.ccode.dev/v1",
        "key_env": "LLM_CCODE_API_KEY",
    }
    warnings = " ".join(converted["warnings"])
    assert "openrouter" in warnings and "цены не переносятся" in warnings


def test_result_is_a_valid_routing_v1():
    converted = legacy.convert(legacy.read(CONFIG))
    parsed = routing_mod.parse(converted["routing"], require_chain=False)
    assert sorted(parsed.providers) == ["anymodel", "ccode"]


def test_levels_and_dropped_sections_are_reported():
    converted = legacy.convert(legacy.read(CONFIG))
    assert converted["levels"]["strong"] == [
        "ccode/gpt-6-astra",
        "openrouter/anthropic/claude-opus-5.5",
        "openrouter/openai/gpt-6-sol",
    ]
    assert converted["dropped"] == ["budget", "cache", "defaults", "retry"]


def test_cli_import_prints_the_routing_and_warnings():
    result = CliRunner().invoke(app, ["routing", "import", str(CONFIG)])
    assert result.exit_code == 0, result.output
    body = json.loads(result.stdout)
    assert set(body["routing"]["providers"]) == {"ccode", "anymodel"}
    assert "не переносятся" in result.stderr
