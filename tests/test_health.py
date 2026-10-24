"""`llm auth status`: форма отчёта §8 (общий контракт инструментов), статусы и коды выхода.

Форма — контракт с `tools-watch`: поменять её — ломающее изменение.
"""

from __future__ import annotations

import json

import httpx
import pytest
from conftest import ROUTING
from typer.testing import CliRunner

from llmkit import health
from llmkit import keys as keys_mod
from llmkit.cli.main import app
from llmkit.providers import KINDS, SUBSCRIPTION_KINDS
from llmkit.transports import chatgpt_auth

runner = CliRunner()
ENTRY_KEYS = {
    "provider",
    "required",
    "fields",
    "source",
    "source_ref",
    "status",
    "expires_at",
    "quota",
    "message",
}
SOURCES = {"env", "keychain", "file", "missing"}
STATUSES = {"ok", "missing", "invalid", "expired", "quota_exhausted", "unreachable", "unchecked"}


@pytest.fixture(autouse=True)
def no_keychain(monkeypatch):
    monkeypatch.setattr(keys_mod, "from_keychain", lambda provider: None)


@pytest.fixture(autouse=True)
def routing_file(tmp_path, monkeypatch):
    """Провайдеры с ключами — из routing пользователя (LLMKIT_ROUTING_FILE)."""
    path = tmp_path / "routing.json"
    path.write_text(json.dumps(ROUTING), encoding="utf-8")
    monkeypatch.setenv("LLMKIT_ROUTING_FILE", str(path))


def status(*args: str):
    result = runner.invoke(app, ["auth", "status", *args, "--json"])
    return result, json.loads(result.stdout)


def by_provider(body: dict) -> dict[str, dict]:
    return {item["provider"]: item for item in body["credentials"]}


def test_report_shape_is_the_cross_tool_contract():
    result, body = status()
    assert result.exit_code == 0, result.output
    assert body["ok"] is True
    assert {"tool", "version", "checked_at", "credentials"} <= body.keys()
    assert body["tool"] == "llmkit" and body["checked_at"].endswith("Z")
    for item in body["credentials"]:
        assert set(item) == ENTRY_KEYS
        assert item["source"] in SOURCES and item["status"] in STATUSES
        assert item["required"] is False


def test_presence_without_check(monkeypatch):
    _, body = status()
    items = by_provider(body)
    assert items["a"]["source"] == "env" and items["a"]["source_ref"] == "TEST_A_KEY"
    assert items["a"]["status"] == "unchecked"
    assert items["chatgpt"]["status"] == "missing" and items["chatgpt"]["source"] == "missing"
    assert items["claude"]["status"] == "missing"  # CLAUDE_COMMAND указывает в пустоту


def test_values_never_leave_the_report(monkeypatch):
    monkeypatch.setattr(health, "check_key", lambda kind, key, base, **kw: health.Health("invalid", message=key))
    result, body = status("--check", "--provider", "a")
    assert "ключ-a" not in result.stdout
    assert by_provider(body)["a"]["message"] == "***"


def test_invalid_key_exits_3_with_report_inside_error_envelope(monkeypatch):
    monkeypatch.setattr(health, "check_key", lambda *a, **kw: health.Health("invalid", message="HTTP 401"))
    result, body = status("--check", "--provider", "a")
    assert result.exit_code == 3
    assert body["ok"] is False and body["error"]["code"] == "CREDENTIALS_UNHEALTHY"
    assert by_provider(body)["a"]["status"] == "invalid"


def test_unreachable_optional_provider_keeps_exit_0(monkeypatch):
    monkeypatch.setattr(health, "check_key", lambda *a, **kw: health.Health("unreachable", message="timeout"))
    result, body = status("--check", "--provider", "a")
    assert result.exit_code == 0 and body["ok"] is True


def test_unknown_provider_is_usage_error():
    result, body = status("--provider", "nope")
    assert result.exit_code == 2 and body["error"]["code"] == "INVALID_ARGUMENTS"


def test_chatgpt_login_file_is_reported_as_file():
    chatgpt_auth.write_auth(chatgpt_auth.Auth(access_token="t", refresh_token="r"), chatgpt_auth.default_path())
    _, body = status("--provider", "chatgpt")
    item = by_provider(body)["chatgpt"]
    assert item["source"] == "file" and item["source_ref"] == str(chatgpt_auth.default_path())
    assert item["status"] == "unchecked"


def test_every_key_kind_has_a_check():
    """Аналог контракта шаблона «у каждого провайдера есть health_check()»."""
    key_kinds = set(KINDS) - SUBSCRIPTION_KINDS
    assert key_kinds <= set(health._KEY_CHECKS), f"нет проверки для: {sorted(key_kinds - set(health._KEY_CHECKS))}"


def test_without_routing_only_subscriptions_are_listed(monkeypatch):
    monkeypatch.delenv("LLMKIT_ROUTING_FILE")
    result, body = status()
    assert result.exit_code == 0
    assert set(by_provider(body)) == {"chatgpt", "claude"}


@pytest.mark.parametrize(
    ("code", "expected"),
    [(200, "ok"), (401, "invalid"), (403, "invalid"), (429, "unreachable"), (503, "unreachable")],
)
def test_http_status_mapping(code, expected):
    transport = httpx.MockTransport(lambda request: httpx.Response(code, json={}))
    assert health.check_key("openai_compatible", "k", "https://gw.example/v1", transport=transport).status == expected


def test_network_error_is_unreachable():
    def fail(request):
        raise httpx.ConnectError("нет сети")

    got = health.check_key("openai", "k", None, transport=httpx.MockTransport(fail))
    assert got.status == "unreachable" and "нет сети" in (got.message or "")


def test_ollama_checks_the_key_not_the_open_model_list():
    seen = []

    def handler(request):
        seen.append((request.method, str(request.url), request.headers["authorization"]))
        return httpx.Response(200, json={})

    health.check_key("ollama", "k", "https://ollama.com", transport=httpx.MockTransport(handler))
    assert seen == [("POST", "https://ollama.com/api/me", "Bearer k")]


def test_openrouter_reports_quota_and_exhaustion():
    def reply(remaining):
        body = {"data": {"limit": 10, "limit_remaining": remaining}}
        return httpx.MockTransport(lambda request: httpx.Response(200, json=body))

    ok = health.check_key("openrouter", "k", None, transport=reply(4.5))
    assert ok.status == "ok" and ok.quota == {"remaining": 4.5, "limit": 10, "unit": "usd"}
    assert health.check_key("openrouter", "k", None, transport=reply(0)).status == "quota_exhausted"


def test_expired_health_becomes_expired():
    from datetime import UTC, datetime

    item = health._apply(
        health._blank("x", ["api_key"], "X"), health.Health(expires_at=datetime(2020, 1, 1, tzinfo=UTC)), []
    )
    assert item["status"] == "expired" and item["expires_at"] == "2020-01-01T00:00:00Z"
    assert health.is_problem(item)


def fake_claude_status(monkeypatch, **status):
    from llmkit.transports import claude_cli

    async def auth_status(timeout: float = 20.0) -> dict:
        return {"installed": True, "loggedIn": False, **status}

    monkeypatch.setattr(claude_cli, "auth_status", auth_status)


def test_claude_logged_in_is_checked_locally(monkeypatch):
    fake_claude_status(monkeypatch, loggedIn=True, authMethod="claude.ai", subscriptionType="max")
    _, plain = status("--provider", "claude")
    assert by_provider(plain)["claude"]["status"] == "unchecked"
    _, checked = status("--check", "--provider", "claude")
    item = by_provider(checked)["claude"]
    assert item["status"] == "ok" and item["message"].startswith("claude.ai; max")


def test_claude_not_answering_is_unreachable(monkeypatch):
    fake_claude_status(monkeypatch, error="claude auth status не ответил за 10 с")
    result, body = status("--check", "--provider", "claude")
    assert result.exit_code == 0 and by_provider(body)["claude"]["status"] == "unreachable"


def logged_in_chatgpt():
    chatgpt_auth.write_auth(
        chatgpt_auth.Auth(access_token="секрет-доступа", refresh_token="секрет-обновления", plan_type="plus"),
        chatgpt_auth.default_path(),
    )


def test_chatgpt_check_ok(monkeypatch):
    logged_in_chatgpt()

    async def access(self, client):
        return chatgpt_auth.read_auth(self.path)

    monkeypatch.setattr(chatgpt_auth.TokenStore, "access", access)
    _, body = status("--check", "--provider", "chatgpt")
    item = by_provider(body)["chatgpt"]
    assert item["status"] == "ok" and "план: plus" in item["message"]


def test_chatgpt_rejected_refresh_is_invalid_and_scrubbed(monkeypatch):
    logged_in_chatgpt()

    async def access(self, client):
        raise chatgpt_auth.SubscriptionAuthError("отказ для секрет-обновления")

    monkeypatch.setattr(chatgpt_auth.TokenStore, "access", access)
    result, body = status("--check", "--provider", "chatgpt")
    assert result.exit_code == 3 and "секрет-обновления" not in result.stdout
    assert by_provider(body)["chatgpt"]["status"] == "invalid"


def test_human_output_line_per_provider_and_error_on_stderr(monkeypatch):
    monkeypatch.setattr(health, "check_key", lambda *a, **kw: health.Health("invalid", message="HTTP 401"))
    result = runner.invoke(app, ["auth", "status", "--check", "--provider", "a"])
    assert result.exit_code == 3
    assert "a: invalid (env: TEST_A_KEY)" in result.stdout
    assert "CREDENTIALS_UNHEALTHY" not in result.stdout and "проблемы с доступом" in result.stderr


def test_check_timeout_is_unreachable(monkeypatch):
    import time

    monkeypatch.setattr(health, "CHECK_TIMEOUT", 0.05)
    got = health._with_timeout(lambda: time.sleep(0.5) or health.Health())
    assert got.status == "unreachable"


def test_human_output_is_the_same_in_ci(same_in_ci) -> None:
    same_in_ci("test_human_output_line_per_provider_and_error_on_stderr")
