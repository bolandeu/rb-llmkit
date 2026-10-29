"""`llm doctor`: отчёт о готовности к работе (Standard, Health) — форма и проверки, без сети."""

from __future__ import annotations

import json

from conftest import ROUTING
from typer.testing import CliRunner

from llmkit.cli.main import app

runner = CliRunner()


def doctor(*args: str) -> dict:
    result = runner.invoke(app, ["doctor", "--json", *args])
    assert result.exit_code == 0, result.output  # отчёт — результат, даже если не здоров
    return json.loads(result.stdout)


def checks(report: dict) -> dict[str, dict]:
    return {check["name"]: check for check in report["checks"]}


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
    assert {"version", "config", "routing", "usage-db", "external:claude"} <= names


def test_missing_routing_is_unhealthy_but_exit_zero():
    found = checks(doctor())
    assert found["routing"]["ok"] is False
    assert "llm routing" in found["routing"]["detail"] or "--routing" in found["routing"]["detail"]


def test_valid_routing_is_ok(tmp_path, monkeypatch):
    path = tmp_path / "routing.json"
    path.write_text(json.dumps(ROUTING))
    monkeypatch.setenv("LLMKIT_ROUTING_FILE", str(path))
    assert checks(doctor())["routing"]["ok"] is True


def test_broken_routing_is_reported_not_raised(tmp_path, monkeypatch):
    path = tmp_path / "routing.json"
    path.write_text("{не json")
    monkeypatch.setenv("LLMKIT_ROUTING_FILE", str(path))
    found = checks(doctor())
    assert found["routing"]["ok"] is False and found["routing"]["detail"]


def test_optional_external_program_missing_does_not_fail():
    claude = checks(doctor())["external:claude"]  # conftest: CLAUDE_COMMAND указывает в никуда
    assert claude["ok"] is True
    assert "не найден" in claude["detail"]


def test_usage_db_is_ok_on_a_fresh_local_database():
    assert checks(doctor())["usage-db"]["ok"] is True


def test_cache_line_reports_the_database_error_not_a_file_path(monkeypatch):
    monkeypatch.setenv("LLMKIT_DATABASE_URL", "postgresql+psycopg://user:pw@127.0.0.1:1/llmkit")
    cache = checks(doctor())["cache"]
    assert cache["ok"] is False
    assert "OperationalError" in cache["detail"] or "DatabaseUnavailable" in cache["detail"]
    assert "cache.sqlite" not in cache["detail"]


def test_cache_line_names_the_local_database_when_ready():
    cache = checks(doctor())["cache"]
    assert cache["ok"] is True and "usage.sqlite" in cache["detail"]
