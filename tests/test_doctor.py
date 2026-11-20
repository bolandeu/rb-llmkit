"""`llm doctor`: отчёт о готовности к работе (Standard, Health) — форма и проверки, без сети."""

from __future__ import annotations

import json

import httpx
from conftest import GATEWAY_ROUTING
from typer.testing import CliRunner

from rb_llmkit import doctor as doctor_mod
from rb_llmkit.cli.main import app

runner = CliRunner()


def doctor(*args: str) -> dict:
    result = runner.invoke(app, ["doctor", "--json", *args])
    assert result.exit_code == 0, result.output  # отчёт — результат, даже если не здоров
    return json.loads(result.stdout)


def checks(report: dict) -> dict[str, dict]:
    return {check["name"]: check for check in report["checks"]}


def routing_file(tmp_path, monkeypatch, base_url: str) -> str:
    """Routing с тем же провайдером, но по адресу настоящего шлюза."""
    routing = {
        **GATEWAY_ROUTING,
        "providers": {"9router": {**GATEWAY_ROUTING["providers"]["9router"], "base_url": base_url}},
    }
    path = tmp_path / "routing.json"
    path.write_text(json.dumps(routing), encoding="utf-8")
    monkeypatch.setenv("LLMKIT_ROUTING_FILE", str(path))
    monkeypatch.setenv("NINEROUTER_API_KEY", "ключ-шлюза")
    return base_url


def answers(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"data": []})


def refuses(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("connection refused")


def test_report_shape():
    report = doctor()
    assert report["ok"] is True
    assert isinstance(report["healthy"], bool)
    for check in report["checks"]:
        assert set(check) <= {"name", "ok", "detail"}
        assert isinstance(check["name"], str) and isinstance(check["ok"], bool)
    assert report["healthy"] == all(check["ok"] for check in report["checks"])


def test_checks_cover_what_llm_needs():
    names = set(checks(doctor()))
    assert {"version", "config", "routing", "gateway"} <= names


def test_missing_routing_is_unhealthy_but_exit_zero():
    found = checks(doctor())
    assert found["routing"]["ok"] is False
    assert "llm routing" in found["routing"]["detail"] or "--routing" in found["routing"]["detail"]


def test_valid_routing_is_ok(tmp_path, monkeypatch):
    path = tmp_path / "routing.json"
    path.write_text(json.dumps(GATEWAY_ROUTING))
    monkeypatch.setenv("LLMKIT_ROUTING_FILE", str(path))
    assert checks(doctor())["routing"]["ok"] is True


def test_broken_routing_is_reported_not_raised(tmp_path, monkeypatch):
    path = tmp_path / "routing.json"
    path.write_text("{не json")
    monkeypatch.setenv("LLMKIT_ROUTING_FILE", str(path))
    found = checks(doctor())
    assert found["routing"]["ok"] is False and found["routing"]["detail"]


def test_gateway_check_is_ok_when_the_gateway_answers(tmp_path, monkeypatch):
    routing_file(tmp_path, monkeypatch, "http://gateway.test/v1")
    report = doctor_mod.report(transport=httpx.MockTransport(answers))
    assert checks(report)["gateway"]["ok"] is True
    assert report["healthy"] is True


def test_gateway_check_names_the_url_when_the_gateway_is_down(tmp_path, monkeypatch):
    routing_file(tmp_path, monkeypatch, "http://gateway.test/v1")
    report = doctor_mod.report(transport=httpx.MockTransport(refuses))
    assert report["healthy"] is False
    gateway = checks(report)["gateway"]
    assert gateway["ok"] is False and "http://gateway.test/v1" in gateway["detail"]


def test_cli_doctor_checks_the_gateway(tmp_path, monkeypatch, gateway_server):
    """`llm doctor --json` доходит до шлюза: локальный HTTP-сервер на 127.0.0.1 отвечает как живой."""
    routing_file(tmp_path, monkeypatch, f"{gateway_server}/v1")
    report = doctor()
    assert report["healthy"] is True
    assert checks(report)["gateway"]["ok"] is True


def test_cli_doctor_reports_a_gateway_that_does_not_answer(tmp_path, monkeypatch):
    url = routing_file(tmp_path, monkeypatch, "http://127.0.0.1:9/v1")
    report = doctor()
    assert report["healthy"] is False
    gateway = checks(report)["gateway"]
    assert gateway["ok"] is False and url in gateway["detail"]
