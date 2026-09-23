"""Подписка Claude через CLI: вместо `claude` — поддельный скрипт, сети нет."""

from __future__ import annotations

import json
import sys
import textwrap
import time

import pytest

from llmkit.transports import _common, claude_cli

FAKE_CLI = textwrap.dedent(
    """\
    import json, os, sys, time
    record = {"argv": sys.argv[1:], "stdin": sys.stdin.read(),
              "env": {k: os.environ.get(k) for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL",
                      "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_MAX_RETRIES", "CLAUDE_CODE_MAX_OUTPUT_TOKENS",
                      "CLAUDE_CODE_OAUTH_TOKEN")},
              "cwd": os.getcwd()}
    argv = sys.argv[1:]
    record["system"] = open(argv[argv.index("--system-prompt-file") + 1]).read()
    with open(os.environ["FAKE_RECORD"], "w") as fh:
        json.dump(record, fh)
    if os.environ.get("FAKE_SLEEP"):
        time.sleep(float(os.environ["FAKE_SLEEP"]))
    print(os.environ["FAKE_OUTPUT"])
    """
)


@pytest.fixture
def fake_cli(tmp_path, monkeypatch):
    script = tmp_path / "fake_claude.py"
    script.write_text(FAKE_CLI, "utf-8")
    record = tmp_path / "record.json"
    monkeypatch.setenv("CLAUDE_COMMAND", f"{sys.executable} {script}")
    monkeypatch.setenv("FAKE_RECORD", str(record))

    def install(output: dict) -> callable:
        monkeypatch.setenv("FAKE_OUTPUT", json.dumps(output))
        return lambda: json.loads(record.read_text("utf-8"))

    return install


def result(text: str = "понг", **extra) -> dict:
    return {
        "type": "result", "subtype": "success", "is_error": False, "result": text,
        "usage": {"input_tokens": 10, "cache_read_input_tokens": 5, "output_tokens": 3},
        "stop_reason": "end_turn", **extra,
    }  # fmt: skip


async def call(**kwargs):
    kwargs.setdefault("messages", [{"role": "system", "content": "будь краток"}, {"role": "user", "content": "пинг"}])
    return await claude_cli.acompletion(model="sonnet", timeout=30, **kwargs)


async def test_one_shot_call_without_tools_and_foreign_keys(fake_cli, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "платный-ключ")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://proxy")
    monkeypatch.setenv("CLAUDE_CODE_USE_BEDROCK", "1")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "токен-подписки")
    recorded = fake_cli(result())
    response = await call(max_tokens=200)
    seen = recorded()
    assert response.choices[0].message.content == "понг"
    assert (response.usage.prompt_tokens, response.usage.completion_tokens) == (15, 3)
    argv = seen["argv"]
    assert argv[argv.index("--tools") + 1] == "" and argv[argv.index("--max-turns") + 1] == "1"
    assert "--no-session-persistence" in argv and argv[argv.index("--model") + 1] == "sonnet"
    assert seen["system"] == "будь краток" and seen["stdin"] == "пинг"
    assert seen["env"] == {
        "ANTHROPIC_API_KEY": None, "ANTHROPIC_BASE_URL": None, "CLAUDE_CODE_USE_BEDROCK": None,
        "CLAUDE_CODE_MAX_RETRIES": "0", "CLAUDE_CODE_MAX_OUTPUT_TOKENS": "200",
        "CLAUDE_CODE_OAUTH_TOKEN": "токен-подписки",
    }  # fmt: skip
    assert "llmkit-claude-" in seen["cwd"]  # пустой каталог: чужой CLAUDE.md не подхватится


async def test_json_schema_goes_native_and_structured_output_wins(fake_cli):
    recorded = fake_cli(result("```json\n{}\n```", structured_output={"name": "Яблоко"}))
    schema = {"type": "object", "properties": {"name": {"type": "string"}}}
    response = await call(response_format={"type": "json_schema", "json_schema": {"name": "F", "schema": schema}})
    argv = recorded()["argv"]
    assert json.loads(argv[argv.index("--json-schema") + 1]) == schema
    assert json.loads(response.choices[0].message.content) == {"name": "Яблоко"}


async def test_history_becomes_transcript(fake_cli):
    recorded = fake_cli(result())
    await call(messages=[
        {"role": "user", "content": "раз"}, {"role": "assistant", "content": "два"}, {"role": "user", "content": "три"},
    ])  # fmt: skip
    stdin = recorded()["stdin"]
    assert "User: раз" in stdin and "Assistant: два" in stdin and stdin.endswith("три")


@pytest.mark.parametrize(
    ("output", "error"),
    [
        (result("API Error: 429 rate limited", is_error=True, api_error_status=429), _common.SubscriptionRateLimit),
        (result("Not logged in · Please run /login", is_error=True), _common.SubscriptionAuthError),
        (result("API Error: 529 overloaded", is_error=True), _common.SubscriptionServerError),
        (result("Prompt is too long", is_error=True), _common.SubscriptionContextLength),
        (result(""), _common.SubscriptionEmpty),
    ],
)
async def test_cli_errors_are_classified(fake_cli, output, error):
    fake_cli(output)
    with pytest.raises(error):
        await call()


async def test_timeout_kills_the_cli(fake_cli, monkeypatch):
    fake_cli(result())
    monkeypatch.setenv("FAKE_SLEEP", "30")
    started = time.monotonic()
    with pytest.raises(_common.SubscriptionTimeout):
        await claude_cli.acompletion(model="sonnet", messages=[{"role": "user", "content": "x"}], timeout=0.5)
    assert time.monotonic() - started < 10


async def test_missing_cli_is_auth_error(monkeypatch):
    monkeypatch.setenv("CLAUDE_COMMAND", "llmkit-no-such-claude")
    with pytest.raises(_common.SubscriptionAuthError, match="не найден"):
        await call()
