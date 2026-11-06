"""`llm cost --since/--until` с датой (ГГГГ-ММ-ДД) — регрессия на отчёт ревью LLMKIT-010.

Журнал — SQLite шлюза с фиксированными датами: проверка границ дня не зависит
от «сейчас». Схема — только те колонки, которые читает запрос.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from test_cost import cost

KEY_A = "sk-дата-а"
KEY_B = "sk-дата-б"


@pytest.fixture
def dated_gateway(tmp_path, monkeypatch) -> Path:
    """Журнал шлюза на фиксированных датах, путь — в `LLMKIT_GATEWAY_DB`."""
    path = tmp_path / "dated.sqlite"
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE usageHistory ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL, apiKey TEXT,"
            " promptTokens INTEGER DEFAULT 0, completionTokens INTEGER DEFAULT 0, cost REAL DEFAULT 0)"
        )
        connection.executemany(
            "INSERT INTO usageHistory (timestamp, apiKey, promptTokens, completionTokens, cost) VALUES (?, ?, ?, ?, ?)",
            [
                ("2026-11-05T00:00:00.000Z", KEY_A, 1, 1, 0.10),
                ("2026-11-05T23:59:59.999Z", KEY_B, 2, 2, 0.20),
                ("2026-11-06T00:00:00.000Z", KEY_A, 4, 4, 0.40),
            ],
        )
    monkeypatch.setenv("LLMKIT_GATEWAY_DB", str(path))
    return path


@pytest.mark.usefixtures("dated_gateway")
def test_since_takes_a_date():
    """`--since 2026-11-06` — с начала дня: строки 5 ноября вне периода."""
    result, body = cost("--since", "2026-11-06")
    assert result.exit_code == 0, result.output
    assert {row["key"]: row["calls"] for row in body["rows"]} == {KEY_A: 1}


@pytest.mark.usefixtures("dated_gateway")
def test_until_takes_a_whole_date():
    """`--until 2026-11-05` закрывает весь день, включая 23:59:59.999."""
    result, body = cost("--until", "2026-11-05")
    assert result.exit_code == 0, result.output
    assert {row["key"]: row["calls"] for row in body["rows"]} == {KEY_A: 1, KEY_B: 1}


@pytest.mark.usefixtures("dated_gateway")
def test_timestamp_is_not_a_period():
    """Контракт обещает дату без времени: метка времени — неверный период, код 2."""
    result, body = cost("--since", "2026-11-05T00:00:00Z")
    assert result.exit_code == 2
    assert body["ok"] is False
