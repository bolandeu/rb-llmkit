"""`llm cost --json`: расходы из журнала шлюза — только чтение, без своего учёта.

Журнал — SQLite шлюза 9router: таблица `usageHistory` (строка на запрос) и
`usageDaily` (агрегат дня, JSON-поле `data`). llmkit её не пишет и не мигрирует;
потребителя различает ключ шлюза из колонки `apiKey`. Путь к файлу —
`LLMKIT_GATEWAY_DB`, по умолчанию `~/.9router/db/data.sqlite`.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from typer.testing import CliRunner

from rb_llmkit.cli.main import app

runner = CliRunner()

# Схема шлюза как есть (`~/.9router/db/data.sqlite`): timestamp — ISO 8601 UTC строкой.
SCHEMA = """
CREATE TABLE usageHistory (
    id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL, provider TEXT, model TEXT,
    connectionId TEXT, apiKey TEXT, endpoint TEXT, promptTokens INTEGER DEFAULT 0,
    completionTokens INTEGER DEFAULT 0, cost REAL DEFAULT 0, status TEXT, tokens TEXT, meta TEXT
);
CREATE TABLE usageDaily (dateKey TEXT PRIMARY KEY, data TEXT NOT NULL);
"""

KEY_A = "sk-потребитель-а"
KEY_B = "sk-потребитель-б"


def _stamp(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _daily(request_a: int, request_b: int) -> dict:
    """День в форме шлюза: `byApiKey` — «ключ|модель|провайдер» → числа (сверено с живым журналом)."""
    return {
        "byApiKey": {
            f"{KEY_A}|deepseek/deepseek-v4.1-flash-1017|openrouter": {"apiKey": KEY_A, "requests": request_a},
            f"{KEY_B}|deepseek/deepseek-v4.1-flash-1017|openrouter": {"apiKey": KEY_B, "requests": request_b},
        }
    }


@pytest.fixture
def gateway_db(tmp_path, monkeypatch) -> Path:
    """Журнал шлюза: два ключа за последний день и строка вне `--since 1d`."""
    now = datetime.now(UTC)
    path = tmp_path / "gateway.sqlite"
    rows = [
        (now - timedelta(minutes=1), KEY_A, 10, 5, 0.02),
        (now - timedelta(minutes=5), KEY_A, 4, 1, 0.01),
        (now - timedelta(hours=2), KEY_B, 7, 3, 0.05),
        (now - timedelta(days=3), KEY_A, 100, 100, 1.0),  # вне периода
    ]
    with sqlite3.connect(path) as connection:
        connection.executescript(SCHEMA)
        connection.executemany(
            "INSERT INTO usageHistory (timestamp, provider, model, apiKey, promptTokens, completionTokens, cost,"
            " status) VALUES (?, 'openrouter', 'deepseek/deepseek-v4.1-flash-1017', ?, ?, ?, ?, 'ok')",
            [(_stamp(moment), key, prompt, completion, cost) for moment, key, prompt, completion, cost in rows],
        )
        connection.execute(
            "INSERT INTO usageDaily (dateKey, data) VALUES (?, ?)",
            (now.date().isoformat(), json.dumps(_daily(2, 1))),
        )
    monkeypatch.setenv("LLMKIT_GATEWAY_DB", str(path))
    return path


def cost(*args: str):
    result = runner.invoke(app, ["cost", *args, "--json"])
    return result, json.loads(result.stdout)


@pytest.mark.usefixtures("gateway_db")
def test_spend_is_grouped_by_gateway_key():
    result, body = cost("--since", "1d")
    assert result.exit_code == 0, result.output
    assert body["ok"] is True
    rows = {row["key"]: row for row in body["rows"]}
    assert set(rows) == {KEY_A, KEY_B}
    assert rows[KEY_A]["calls"] == 2 and rows[KEY_A]["cost_usd"] == pytest.approx(0.03)
    assert rows[KEY_A]["prompt_tokens"] == 14 and rows[KEY_A]["completion_tokens"] == 6
    assert rows[KEY_B]["calls"] == 1 and rows[KEY_B]["cost_usd"] == pytest.approx(0.05)
    assert body["total"]["calls"] == 3 and body["total"]["cost_usd"] == pytest.approx(0.08)


def test_gateway_journal_is_opened_read_only(gateway_db):
    before_files = sorted(path.name for path in gateway_db.parent.iterdir())
    before = (gateway_db.stat().st_mtime_ns, gateway_db.read_bytes())
    result, body = cost("--since", "1d")
    assert result.exit_code == 0 and body["ok"] is True
    assert (gateway_db.stat().st_mtime_ns, gateway_db.read_bytes()) == before
    # Ни журнала транзакций, ни -wal рядом: файл не открывали на запись.
    assert sorted(path.name for path in gateway_db.parent.iterdir()) == before_files


def test_missing_gateway_database_is_unavailable(tmp_path, monkeypatch):
    missing = tmp_path / "нет-журнала.sqlite"
    monkeypatch.setenv("LLMKIT_GATEWAY_DB", str(missing))
    result, body = cost()
    assert result.exit_code == 5
    assert body["ok"] is False
    assert str(missing) in json.dumps(body, ensure_ascii=False)  # подсказка называет путь


@pytest.mark.usefixtures("gateway_db")
def test_tags_grouping_is_gone():
    result, _ = cost("--by", "tool")
    assert result.exit_code == 2


# --- период: смещение назад, дата и метка времени -----------------------------------

DATED_ROWS = [
    # (timestamp шлюза, цена): даты фиксированы, ожидаемые суммы посчитаны руками.
    ("2026-10-31T23:59:59.000Z", 0.10),
    ("2026-11-01T00:00:00.000Z", 0.01),
    ("2026-11-01T12:00:00.000Z", 0.02),
    ("2026-11-02T12:00:00.000Z", 0.20),
]


@pytest.fixture
def dated_gateway_db(tmp_path, monkeypatch) -> Path:
    """Журнал с фиксированными датами (ноябрь 2026): период не зависит от «сейчас»."""
    path = tmp_path / "dated.sqlite"
    with sqlite3.connect(path) as connection:
        connection.executescript(SCHEMA)
        connection.executemany(
            "INSERT INTO usageHistory (timestamp, provider, model, apiKey, promptTokens, completionTokens, cost,"
            " status) VALUES (?, 'openrouter', 'deepseek/deepseek-v4.1-flash-1017', ?, 1, 1, ?, 'ok')",
            [(stamp, KEY_A, price) for stamp, price in DATED_ROWS],
        )
    monkeypatch.setenv("LLMKIT_GATEWAY_DB", str(path))
    return path


def test_date_only_period_selects_the_whole_day(dated_gateway_db):
    """`--since 2026-11-01 --until 2026-11-01` — день 1 ноября целиком, без INVALID_ARGUMENTS."""
    result, body = cost("--since", "2026-11-01", "--until", "2026-11-01")
    assert result.exit_code == 0, result.output
    assert body["total"]["calls"] == 2
    assert body["total"]["cost_usd"] == pytest.approx(0.03)


def test_iso_timestamp_bounds_cut_inside_a_day(dated_gateway_db):
    """Граница меткой времени ISO 8601 режет день по часам, а не только по датам."""
    result, body = cost("--since", "2026-11-01T06:00:00Z", "--until", "2026-11-01T23:00:00Z")
    assert result.exit_code == 0, result.output
    assert body["total"]["calls"] == 1
    assert body["total"]["cost_usd"] == pytest.approx(0.02)


def test_a_period_in_neither_form_is_rejected(dated_gateway_db):
    """Ниже обещанного формата — код 2 и подсказка с форматом."""
    result, body = cost("--since", "вчера")
    assert result.exit_code == 2
    assert body["error"]["code"] == "INVALID_ARGUMENTS"
    assert "7d" in body["error"].get("action", "")
