"""Журнал вызовов: строки, окна времени, отчёты и бюджеты."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from llmkit.usage import Usage, parse_since


@pytest.fixture
def journal(tmp_path):
    return Usage(tmp_path / "usage.sqlite")


def test_parse_since_accepts_relative_and_absolute():
    assert parse_since(None) is None
    moment = datetime.now(UTC) - timedelta(days=1)
    assert parse_since(moment) == moment.timestamp()
    assert parse_since("7d") == pytest.approx((datetime.now(UTC) - timedelta(days=7)).timestamp(), abs=2)
    assert parse_since("12h") == pytest.approx((datetime.now(UTC) - timedelta(hours=12)).timestamp(), abs=2)
    with pytest.raises(ValueError, match="период"):
        parse_since("позавчера")


def test_report_counts_statuses(journal):
    journal.record(model="a/m1", provider="a", status="ok", tags={"tool": "t"}, prompt_tokens=10, cost_usd=0.5)
    journal.record(model="a/m1", provider="a", status="cache", tags={"tool": "t"})
    journal.record(model="a/m1", provider="a", status="failed", tags={"tool": "t"}, error_type="timeout")
    journal.record(model="b/m2", provider="b", status="ok", tags={"tool": "другой"}, cost_usd=0.25)
    rows = {row.keys["tool"]: row for row in journal.report(("tool",))}
    assert rows["t"].calls == 3 and rows["t"].cached == 1 and rows["t"].failed == 1
    assert rows["t"].prompt_tokens == 10 and rows["t"].cost_usd == 0.5
    total = journal.total()
    assert total.calls == 4 and total.cost_usd == 0.75


def test_report_window_filters_old_rows(journal):
    journal.record(model="a/m1", provider="a", status="ok", cost_usd=1.0)
    with journal._connect() as connection:
        connection.execute("UPDATE calls SET ts = ts - ?", (10 * 86400,))
    assert journal.total(since="7d").calls == 0
    assert journal.total().calls == 1


def test_spent_today_by_tag(journal):
    journal.record(model="a/m1", provider="a", status="ok", tags={"tool": "t"}, cost_usd=1.5)
    journal.record(model="a/m1", provider="a", status="ok", tags={"tool": "другой"}, cost_usd=2.0)
    assert journal.spent_today() == 3.5
    assert journal.spent_today(tag="tool=t") == 1.5
    assert journal.spent_today(tag="tool=нет") == 0.0
