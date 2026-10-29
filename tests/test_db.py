"""Слой БД (llmkit.db): SQLite мигрируется при открытии, общая PostgreSQL — только `llm db upgrade`."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from typer.testing import CliRunner

from llmkit import db
from llmkit.cli.main import app
from llmkit.db import tables
from llmkit.errors import DatabaseNotMigrated, DatabaseTooNew, DatabaseUnavailable, InvalidArguments
from llmkit.usage import Usage

runner = CliRunner()

# Настоящий контракт PostgreSQL (advisory lock, последовательности, psycopg, JSONB) —
# только на одноразовом сервере, который поднимает scripts/pg_test.sh и называет в TEST_DATABASE_URL.
PG_URL = os.environ.get("TEST_DATABASE_URL")

LEGACY_SCHEMA = (
    "CREATE TABLE calls (id INTEGER PRIMARY KEY, ts REAL, task_id TEXT, tags TEXT, level TEXT, model TEXT,"
    " provider TEXT, status TEXT, error_type TEXT, attempt INTEGER, prompt_tokens INTEGER,"
    " completion_tokens INTEGER, cost_usd REAL, cost_known INTEGER, latency_ms INTEGER, pid INTEGER);"
    "CREATE INDEX calls_ts ON calls (ts); CREATE INDEX calls_status ON calls (status);"
)


@pytest.fixture(autouse=True)
def engines(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[sa.Engine]]:
    """Каждый открытый тестом engine закрывается после него."""
    opened: list[sa.Engine] = []
    sqlite_engine = db.sqlite_engine

    def tracked(file: Path) -> sa.Engine:
        opened.append(sqlite_engine(file))
        return opened[-1]

    monkeypatch.setattr(db, "sqlite_engine", tracked)
    yield opened
    for engine in opened:
        engine.dispose()


@pytest.fixture
def local_path(tmp_path: Path) -> Path:
    """Локальная база — журнал из конфига тестов (conftest: usage.path)."""
    return tmp_path / "usage.sqlite"


def invoke_json(*args: str) -> tuple[int, dict]:
    result = runner.invoke(app, [*args, "--json"])
    return result.exit_code, json.loads(result.stdout)


def _add_call(engine: sa.Engine, model: str = "a/m1", tags: dict | None = None) -> None:
    with engine.begin() as conn:
        conn.execute(sa.insert(tables.calls).values(ts=1.0, model=model, status="ok", tags=tags or {"tool": "т"}))


def _legacy(path: Path, rows: int = 2) -> None:
    with sqlite3.connect(path) as connection:
        connection.executescript(LEGACY_SCHEMA)
        for i in range(rows):
            connection.execute(
                "INSERT INTO calls (ts, tags, model, status, cost_usd) VALUES (?, ?, ?, 'ok', 0.5)",
                (1000.0 + i, json.dumps({"tool": "старый"}, ensure_ascii=False), f"a/m{i}"),
            )
    connection.close()


def test_names_are_namespaced() -> None:
    assert all(table.name.startswith(db.PREFIX) for table in tables.metadata.sorted_tables)
    assert db.PREFIX == "llmkit_"
    assert db.VERSION_TABLE == "alembic_version_llmkit"
    assert db.ENV_VAR == "LLMKIT_DATABASE_URL"


def test_sqlite_is_created_and_migrated_on_open(local_path: Path) -> None:
    engine = db.open_db()
    names = sa.inspect(engine).get_table_names()
    assert db.VERSION_TABLE in names and "alembic_version" not in names
    assert "llmkit_v1_calls" in sa.inspect(engine).get_view_names()
    assert db.schema_state(engine).up_to_date
    assert local_path.is_file()


def test_every_table_has_a_single_column_primary_key() -> None:
    """Без PRIMARY KEY Directus таблицу не покажет и не даст править, составной он не поддерживает.

    Ключ — суррогатный `id`; естественный ключ — UNIQUE. Проверяются и метаданные, и база после миграций.
    """
    for table in tables.metadata.sorted_tables:
        assert len(table.primary_key.columns) == 1, f"{table.name}: PRIMARY KEY должен быть из одной колонки"
    inspector = sa.inspect(db.open_db())
    for name in inspector.get_table_names():
        columns = inspector.get_pk_constraint(name)["constrained_columns"]
        assert len(columns) == 1, f"{name}: PRIMARY KEY должен быть из одной колонки, а он {columns}"


def test_every_table_says_whether_it_is_data_or_cache() -> None:
    for table in tables.metadata.sorted_tables:
        assert table.info.get("kind") in ("data", "cache"), f'{table.name}: нужен info={{"kind": "data" | "cache"}}'


def test_declared_views_exist_with_their_columns() -> None:
    """Каждое представление из tables.views создают миграции — ровно с объявленными колонками."""
    _assert_views_match(db.open_db())


def _assert_views_match(engine: sa.Engine) -> None:
    inspector = sa.inspect(engine)
    existing = set(inspector.get_view_names())
    for view in tables.views.sorted_tables:
        assert view.name.startswith(f"{db.PREFIX}v"), f"{view.name}: имя представления — <tool>_v<N>_<имя>"
        assert view.name in existing, f"{view.name} объявлено в tables.views, но миграции его не создают"
        columns = [column["name"] for column in inspector.get_columns(view.name)]
        assert columns == [column.name for column in view.columns], f"{view.name}: колонки расходятся с tables.views"


def test_tables_match_the_migrations() -> None:
    """tables.py и migrations/versions/ описывают одну схему."""
    engine = db.open_db()
    with engine.connect() as conn:
        context = MigrationContext.configure(
            conn, opts={"include_name": lambda name, type_, *_: type_ != "table" or name.startswith(db.PREFIX)}
        )
        assert compare_metadata(context, tables.metadata) == []


def test_legacy_calls_table_is_renamed_with_its_rows(local_path: Path) -> None:
    _legacy(local_path)
    usage = Usage(local_path)
    usage.record(model="b/m2", provider="b", status="ok", tags={"tool": "новый"}, served_model="m2-1", cost_usd=1.0)
    rows = {row.keys["tool"]: row for row in usage.report(("tool",))}
    assert rows["старый"].calls == 2 and rows["старый"].cost_usd == 1.0
    assert rows["новый"].calls == 1
    usage.close()
    engine = db.sqlite_engine(local_path)
    inspector = sa.inspect(engine)
    assert "calls" not in inspector.get_table_names()
    assert {index["name"] for index in inspector.get_indexes("llmkit_calls")} == {
        "llmkit_calls_ts_ix",
        "llmkit_calls_status_ix",
    }
    with engine.connect() as conn:
        models = conn.exec_driver_sql("SELECT model, served_model FROM llmkit_v1_calls ORDER BY id").all()
    assert models == [("a/m0", None), ("a/m1", None), ("b/m2", "m2-1")]


def test_concurrent_processes_migrate_once(local_path: Path) -> None:
    """Несколько процессов открывают старый журнал разом: один мигрирует, остальные ждут и видят результат."""
    _legacy(local_path, rows=3)
    code = (
        "import sys; from pathlib import Path; from llmkit.usage import Usage;"
        "u = Usage(Path(sys.argv[1])); u.record(model='x/y', provider='x', status='ok'); u.close()"
    )
    env = {key: value for key, value in os.environ.items() if key != db.ENV_VAR}
    processes = [
        subprocess.Popen([sys.executable, "-c", code, str(local_path)], env=env, stderr=subprocess.PIPE)  # noqa: S603
        for _ in range(4)
    ]
    for process in processes:
        _out, err = process.communicate(timeout=60)
        assert process.returncode == 0, err.decode()
    with sqlite3.connect(local_path) as connection:
        assert connection.execute("SELECT count(*) FROM llmkit_calls").fetchone() == (7,)
    connection.close()


def test_url_never_falls_back_to_sqlite(monkeypatch: pytest.MonkeyPatch, local_path: Path) -> None:
    monkeypatch.setenv(db.ENV_VAR, "postgresql://user:secret@127.0.0.1:1/nowhere")
    code, payload = invoke_json("db", "status")
    assert code == 5
    assert payload["error"]["code"] == "DATABASE_UNAVAILABLE"
    assert "secret" not in payload["error"]["message"]
    assert not local_path.exists()


@pytest.mark.parametrize("url", ["sqlite:///x.db", "not a url"])
def test_url_must_be_postgres(url: str) -> None:
    with pytest.raises(DatabaseUnavailable):
        db.postgres_engine(url)


def _as_postgres(monkeypatch: pytest.MonkeyPatch, engine: sa.Engine) -> None:
    """Ветка с URL на SQLite-engine: правила общей базы без сервера."""
    monkeypatch.setenv(db.ENV_VAR, "postgresql://stand-in")
    monkeypatch.setattr(db, "postgres_engine", lambda *_args, **_kwargs: engine)


def test_shared_database_is_never_migrated_implicitly(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    engine = db.sqlite_engine(tmp_path / "shared.db")
    _as_postgres(monkeypatch, engine)
    with pytest.raises(DatabaseNotMigrated) as excinfo:
        db.open_db()
    assert "db upgrade" in (excinfo.value.action or "")
    assert db.schema_state(engine).current is None  # не тронута
    assert db.open_db(check=False) is engine


def test_library_call_reports_unmigrated_shared_database(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Потребитель с URL на несмигрированную базу получает DatabaseNotMigrated, а не молчаливую SQLite."""
    engine = db.sqlite_engine(tmp_path / "shared.db")
    _as_postgres(monkeypatch, engine)
    usage = Usage(tmp_path / "usage.sqlite")
    with pytest.raises(DatabaseNotMigrated):
        usage.record(model="a/m1", provider="a", status="ok")
    assert not (tmp_path / "usage.sqlite").exists()


def test_db_upgrade_migrates_the_shared_database(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    engine = db.sqlite_engine(tmp_path / "shared.db")
    _as_postgres(monkeypatch, engine)
    code, payload = invoke_json("db", "upgrade", "--dry-run")
    assert (code, payload["current"], payload["dry_run"]) == (0, None, True)
    assert db.schema_state(engine).current is None

    code, payload = invoke_json("db", "upgrade")
    assert code == 0
    assert payload["previous"] is None and payload["up_to_date"] is True
    db.open_db()  # сверка проходит

    code, payload = invoke_json("db", "upgrade")
    assert payload["previous"] == payload["head"]


def test_database_newer_than_the_cli(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    engine = db.sqlite_engine(tmp_path / "shared.db")
    db.upgrade(engine)
    with engine.begin() as conn:
        conn.execute(sa.text(f"UPDATE {db.VERSION_TABLE} SET version_num = 'from_the_future'"))  # noqa: S608
    _as_postgres(monkeypatch, engine)
    with pytest.raises(DatabaseTooNew):
        db.open_db()
    with pytest.raises(DatabaseTooNew):
        db.upgrade(engine)  # никогда не «обновлять» до более старой ревизии
    code, payload = invoke_json("db", "upgrade")
    assert code == 6 and payload["error"]["code"] == "CLI_TOO_OLD"


def test_status(local_path: Path) -> None:
    code, payload = invoke_json("db", "status")
    assert code == 0
    assert payload["up_to_date"] is True
    assert str(local_path) in payload["database"]


def test_import_sqlite(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _legacy(tmp_path / "old.db")  # журнал до v0.5.0: импорт сам его смигрирует
    target = db.sqlite_engine(tmp_path / "shared.db")
    db.upgrade(target)
    _as_postgres(monkeypatch, target)

    code, payload = invoke_json("db", "import-sqlite", str(tmp_path / "old.db"), "--dry-run")
    assert code == 0 and payload["rows"] == {"llmkit_calls": 2}
    with target.connect() as conn:
        assert conn.execute(sa.select(sa.func.count()).select_from(tables.calls)).scalar_one() == 0

    code, payload = invoke_json("db", "import-sqlite", str(tmp_path / "old.db"))
    assert code == 0 and payload["rows"] == {"llmkit_calls": 2}
    with target.connect() as conn:
        assert {row.tags["tool"] for row in conn.execute(sa.select(tables.calls))} == {"старый"}

    code, payload = invoke_json("db", "import-sqlite", str(tmp_path / "old.db"))
    assert code == 2 and "не пуста" in payload["error"]["message"]


def test_import_sqlite_rejects_bad_sources(tmp_path: Path) -> None:
    target = db.sqlite_engine(tmp_path / "shared.db")
    with pytest.raises(InvalidArguments, match="нет базы"):
        db.import_sqlite(tmp_path / "missing.db", target)
    db.upgrade(target)
    with pytest.raises(InvalidArguments, match="одна и та же"):
        db.import_sqlite(tmp_path / "shared.db", target)


@pytest.mark.skipif(not PG_URL, reason="TEST_DATABASE_URL не задан")
def test_postgres_round_trip(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    assert PG_URL
    # Тест удаляет таблицы llmkit: только одноразовый локальный сервер.
    assert sa.make_url(PG_URL).host in ("127.0.0.1", "localhost"), "TEST_DATABASE_URL — только из scripts/pg_test.sh"
    monkeypatch.setenv(db.ENV_VAR, PG_URL)
    engine = db.open_db(check=False)
    with engine.begin() as conn:  # с чистого листа: только объекты llmkit
        conn.execute(sa.text("DROP VIEW IF EXISTS llmkit_v1_calls"))
        conn.execute(sa.text(f"DROP TABLE IF EXISTS llmkit_calls, {db.VERSION_TABLE}"))
        conn.execute(sa.text("CREATE TABLE IF NOT EXISTS directus_users (id int)"))  # чужая таблица
    with pytest.raises(DatabaseNotMigrated):
        db.open_db()
    assert db.upgrade(engine).up_to_date
    db.check_schema(engine)
    _assert_views_match(engine)

    _legacy(tmp_path / "old.db")
    assert db.import_sqlite(tmp_path / "old.db", engine) == {"llmkit_calls": 2}
    usage = Usage(tmp_path / "unused.sqlite")
    usage.record(model="b/m2", provider="b", status="ok", tags={"tool": "новый"}, cost_usd=1.0)  # id после импорта
    rows = {row.keys["tool"]: row for row in usage.report(("tool",))}
    assert rows["старый"].calls == 2 and rows["новый"].cost_usd == 1.0
    assert usage.spent_today(tag="tool=новый") == 1.0
    usage.close()
    with engine.connect() as conn:
        assert conn.execute(sa.text("SELECT count(*) FROM llmkit_v1_calls")).scalar_one() == 3
        assert conn.execute(sa.text("SELECT tags->>'tool' FROM llmkit_calls ORDER BY id DESC")).scalar() == "новый"
        assert sa.inspect(conn).has_table("directus_users")
    assert not (tmp_path / "unused.sqlite").exists()
    engine.dispose()


def test_migration_0003_adds_the_cache_table_and_keeps_calls(local_path: Path) -> None:
    engine = db.sqlite_engine(local_path)
    with engine.begin() as connection:
        command.upgrade(db.alembic_config(connection), "0002")
        connection.execute(sa.insert(tables.calls).values(ts=1.0, model="a/m1", status="ok", tags={}))
    assert "llmkit_cache" not in sa.inspect(engine).get_table_names()
    state = db.upgrade(engine)
    assert (state.current, state.head) == ("0003", "0003")
    assert "llmkit_cache" in sa.inspect(engine).get_table_names()
    with engine.connect() as connection:
        assert connection.execute(sa.select(sa.func.count()).select_from(tables.calls)).scalar_one() == 1
    assert tables.cache.info["kind"] == "cache"
