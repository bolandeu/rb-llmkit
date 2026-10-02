"""Провайдеры по подписке в ядре и CLI: вход вместо ключа, свой транспорт, цена 0."""

from __future__ import annotations

import json

import litellm
import pytest
from pydantic import BaseModel
from typer.testing import CliRunner

from llmkit import LlmKit, Task, providers
from llmkit import routing as routing_mod
from llmkit.cli.main import app
from llmkit.errors import LoginMissing
from llmkit.transports import chatgpt, chatgpt_auth, claude_cli

ROUTING = {"providers": {"gpt": {"protocol": "chatgpt"}, "cl": {"protocol": "claude_cli"}}, "chain": ["gpt/gpt-5.5"]}
CONFIG = routing_mod.parse(ROUTING)


def logged_in() -> None:
    chatgpt_auth.write_auth(chatgpt_auth.Auth(access_token="t", refresh_token="r"), chatgpt_auth.default_path())


def reply(text: str, prompt_tokens: int = 7, completion_tokens: int = 2):
    return litellm.ModelResponse(
        model="m",
        choices=[{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
        usage=litellm.Usage(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens, total_tokens=9),
    )


def test_chatgpt_without_login_is_login_missing():
    with pytest.raises(LoginMissing, match="llm auth login gpt"):
        providers.build("gpt/gpt-5.5", CONFIG)


def test_chatgpt_call_uses_own_transport_and_no_key():
    logged_in()
    call = providers.build("gpt/gpt-5.5", CONFIG, env={})
    assert call.completion is chatgpt.acompletion and call.subscription
    assert call.litellm_model == "gpt-5.5" and call.mode == "JSON_SCHEMA"
    assert "api_key" not in call.params


def test_claude_without_cli_is_login_missing():
    with pytest.raises(LoginMissing, match="claude auth login"):
        providers.build("cl/sonnet", CONFIG, env={"PATH": "", "CLAUDE_COMMAND": ""})


@pytest.fixture
def transport(monkeypatch):
    """Подменяет транспорт ChatGPT на уровне модуля — как его увидит ядро."""
    calls: list[dict] = []

    def install(*answers):
        async def fake(**kwargs):
            calls.append(kwargs)
            return answers[min(len(calls), len(answers)) - 1]

        monkeypatch.setattr(chatgpt, "acompletion", fake)
        logged_in()
        return calls

    return install


def kit() -> LlmKit:
    return LlmKit(routing=ROUTING)


async def test_subscription_answer_costs_nothing(transport):
    calls = transport(reply("понг"))
    answer = await kit().ask(Task(user="пинг", chain=["gpt/gpt-5.5"]))
    assert answer.data == "понг" and answer.source == "llm"
    assert (answer.cost_usd, answer.cost_source, answer.prompt_tokens) == (0.0, "subscription", 7)
    assert calls[0]["model"] == "gpt-5.5" and calls[0]["provider"] == "gpt"


class Fruit(BaseModel):
    name: str


async def test_pydantic_schema_goes_as_native_json_schema(transport):
    calls = transport(reply(json.dumps({"name": "Яблоко"})))
    answer = await kit().ask(Task(user="фрукт", schema=Fruit, chain=["gpt/gpt-5.5"]))
    assert answer.data.model_dump() == {"name": "Яблоко"}
    assert calls[0]["response_format"]["type"] == "json_schema"
    assert calls[0]["response_format"]["json_schema"]["schema"]["required"] == ["name"]


async def test_missing_login_falls_through_to_next_model(transport, monkeypatch):
    transport(reply("из claude"))
    chatgpt_auth.delete_auth(chatgpt_auth.default_path())

    async def fake_claude(**kwargs):
        return reply("из claude")

    monkeypatch.setattr(claude_cli, "command", lambda env=None: ["claude"])
    monkeypatch.setattr(claude_cli, "acompletion", fake_claude)
    answer = await kit().ask(Task(user="x", chain=["gpt/gpt-5.5", "cl/sonnet"]))
    assert answer.model == "cl/sonnet"
    assert answer.attempts[0].error_type == "auth" and "llm auth login gpt" in (answer.attempts[0].error or "")


runner = CliRunner()


def test_cli_auth_status_reports_both_subscriptions():
    result = runner.invoke(app, ["auth", "status", "--json"])
    assert result.exit_code == 0, result.output
    rows = {row["provider"]: row for row in json.loads(result.stdout)["credentials"]}
    assert rows["chatgpt"]["status"] == "missing"
    assert rows["claude"]["status"] == "missing" and "не найден" in rows["claude"]["message"]


def test_cli_ask_without_login_exits_3_with_login_hint():
    routing = json.dumps({"providers": {"chatgpt": {"protocol": "chatgpt"}}, "chain": ["chatgpt/gpt-5.5"]})
    result = runner.invoke(app, ["ask", "привет", "--routing", routing, "--json"])
    assert result.exit_code == 3
    assert "llm auth login chatgpt" in json.loads(result.stdout)["error"]["action"]


def test_cli_logout_without_login_is_fine():
    result = runner.invoke(app, ["auth", "logout", "chatgpt", "--json"])
    assert result.exit_code == 0 and json.loads(result.stdout)["logged_out"] is False


def test_cli_login_rejects_key_provider():
    result = runner.invoke(app, ["auth", "login", "a", "--json"])
    assert result.exit_code == 2
