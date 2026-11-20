"""`llm auth status`: форма отчёта §8 (общий контракт инструментов) — ключ шлюза и ничего больше.

Форма — контракт с `tools-watch`: поменять её — ломающее изменение. Подписки
живут в шлюзе, поэтому подписок в отчёте нет: один провайдер — шлюз из routing,
и его ключ.
"""

from __future__ import annotations

import json

import httpx
import pytest
from conftest import GATEWAY_ROUTING
from typer.testing import CliRunner

from rb_llmkit import health
from rb_llmkit.cli.main import app

runner = CliRunner()
VARIABLE = "NINEROUTER_API_KEY"
# Ключ шлюза — латиницей, как настоящий: HTTP-заголовок не принимает другие символы.
KEY = "sk-gateway-test"
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
SOURCES = {"env", "file", "missing"}
STATUSES = {"ok", "missing", "invalid", "expired", "quota_exhausted", "unreachable", "unchecked"}
SUBSCRIPTIONS = {"chatgpt", "claude"}


@pytest.fixture
def routing(tmp_path, monkeypatch):
    """Провайдер шлюза — из routing пользователя (LLMKIT_ROUTING_FILE)."""

    def write(**changes):
        providers = {"9router": {**GATEWAY_ROUTING["providers"]["9router"], **changes}}
        path = tmp_path / "routing.json"
        path.write_text(json.dumps({**GATEWAY_ROUTING, "providers": providers}), encoding="utf-8")
        monkeypatch.setenv("LLMKIT_ROUTING_FILE", str(path))
        return providers

    return write


@pytest.fixture
def gateway_key(monkeypatch):
    monkeypatch.setenv(VARIABLE, KEY)


def status(*args: str):
    result = runner.invoke(app, ["auth", "status", *args, "--json"])
    return result, json.loads(result.stdout)


@pytest.mark.usefixtures("gateway_key")
def test_report_shape_is_the_cross_tool_contract(routing):
    routing()
    result, body = status()
    assert result.exit_code == 0, result.output
    assert body["ok"] is True
    assert {"tool", "version", "checked_at", "credentials"} <= body.keys()
    assert body["tool"] == "llmkit" and body["checked_at"].endswith("Z")
    for item in body["credentials"]:
        assert set(item) == ENTRY_KEYS
        assert item["source"] in SOURCES and item["status"] in STATUSES
        assert item["required"] is False


@pytest.mark.usefixtures("gateway_key")
def test_reports_the_gateway_key_and_no_subscription(routing):
    routing()
    result, body = status()
    assert result.exit_code == 0, result.output
    (item,) = body["credentials"]
    assert item["provider"] == "9router"
    assert (item["source"], item["source_ref"]) == ("env", VARIABLE)
    assert item["status"] == "unchecked"


def test_subscriptions_are_never_reported(monkeypatch):
    """Подписки знает шлюз: без routing в отчёте нечего показывать, кроме шлюза."""
    monkeypatch.delenv("LLMKIT_ROUTING_FILE", raising=False)
    result, body = status()
    assert result.exit_code == 0
    assert SUBSCRIPTIONS & {item["provider"] for item in body["credentials"]} == set()


def test_missing_key_is_reported_as_missing(routing):
    routing()
    _, body = status()
    (item,) = body["credentials"]
    assert (item["source"], item["status"]) == ("missing", "missing")
    assert VARIABLE in item["source_ref"]


@pytest.mark.usefixtures("gateway_key")
def test_value_never_leaves_the_report(routing, monkeypatch):
    routing()
    monkeypatch.setattr(health, "check_key", lambda _kind, key, _base, **_kw: health.Health("invalid", message=key))
    result, body = status("--check")
    assert KEY not in result.stdout
    assert body["credentials"][0]["message"] == "***"


@pytest.mark.usefixtures("gateway_key")
def test_invalid_key_exits_3_with_report_inside_error_envelope(routing, monkeypatch):
    routing()
    monkeypatch.setattr(health, "check_key", lambda *_a, **_kw: health.Health("invalid", message="HTTP 401"))
    result, body = status("--check")
    assert result.exit_code == 3
    assert body["ok"] is False and body["error"]["code"] == "CREDENTIALS_UNHEALTHY"
    assert body["credentials"][0]["status"] == "invalid"


@pytest.mark.usefixtures("gateway_key")
def test_unreachable_gateway_keeps_exit_0(routing, monkeypatch):
    routing()
    monkeypatch.setattr(health, "check_key", lambda *_a, **_kw: health.Health("unreachable", message="timeout"))
    result, body = status("--check")
    assert result.exit_code == 0 and body["ok"] is True


@pytest.mark.usefixtures("gateway_key")
def test_check_asks_the_gateway_and_reports_ok(routing, gateway_server):
    routing(base_url=f"{gateway_server}/v1")
    result, body = status("--check")
    assert result.exit_code == 0, result.output
    assert body["credentials"][0]["status"] == "ok"


@pytest.mark.usefixtures("gateway_key")
def test_check_of_a_closed_port_is_unreachable(routing):
    routing(base_url="http://127.0.0.1:1/v1")
    result, body = status("--check")
    assert result.exit_code == 0
    assert body["credentials"][0]["status"] == "unreachable"


@pytest.mark.parametrize(
    ("code", "expected"),
    [(200, "ok"), (401, "invalid"), (403, "invalid"), (429, "unreachable"), (503, "unreachable")],
)
def test_http_status_mapping(code, expected):
    transport = httpx.MockTransport(lambda _request: httpx.Response(code, json={}))
    assert health.check_key("openai_compatible", "k", "https://gw.example/v1", transport=transport).status == expected


def test_network_error_is_unreachable():
    def fail(_request):
        raise httpx.ConnectError("нет сети")

    got = health.check_key("openai_compatible", "k", "https://gw.example/v1", transport=httpx.MockTransport(fail))
    assert got.status == "unreachable" and "нет сети" in (got.message or "")


@pytest.mark.usefixtures("gateway_key")
def test_human_output_names_the_gateway_and_error_goes_to_stderr(routing, monkeypatch):
    routing()
    monkeypatch.setattr(health, "check_key", lambda *_a, **_kw: health.Health("invalid", message="HTTP 401"))
    result = runner.invoke(app, ["auth", "status", "--check"])
    assert result.exit_code == 3
    assert "9router: invalid" in result.stdout
    assert "CREDENTIALS_UNHEALTHY" not in result.stdout
    assert "проблемы с доступом" in result.stderr


def test_human_output_is_the_same_in_ci(same_in_ci) -> None:
    same_in_ci("test_human_output_names_the_gateway_and_error_goes_to_stderr")
