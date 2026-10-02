"""База llmkit: общая PostgreSQL из `LLMKIT_DATABASE_URL`, иначе локальная SQLite.

Слой взят из шаблона cli-generator v1.4.0 (`core/db.py`, architecture.md §12);
отличия от шаблона перечислены в AGENTS.md.

- URL задан → только PostgreSQL. Недоступна / чужой пароль → `DatabaseUnavailable`
  (выход 5). Никогда не молчаливая подмена на SQLite: записи туда пропали бы из
  общей базы, и никто бы не заметил.
- URL не задан → SQLite: файл журнала из конфига (`usage.path`, по умолчанию
  `usage.sqlite` в каталоге данных) — так потребители без URL работают как раньше.

Схема меняется миграциями Alembic (`migrations/`), ревизия — в своей таблице
`alembic_version_llmkit`. SQLite приводится к последней ревизии при открытии.
PostgreSQL неявно не мигрируется никогда — одна база на все машины, и рабочая копия
не должна её менять: это делает `llm db upgrade` под advisory lock; при открытии
ревизия только сверяется (отстала → `DatabaseNotMigrated`, неизвестна → базу
смигрировал более новый релиз, `DatabaseTooNew`).
"""

from __future__ import annotations

import contextlib
import json
import os
from dataclasses import dataclass
from functools import partial
from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from alembic.script.revision import RevisionError
from alembic.util import CommandError
from sqlalchemy import event
from sqlalchemy import exc as sa_exc

from .._distribution import TOOL
from ..errors import DatabaseNotMigrated, DatabaseTooNew, DatabaseUnavailable, InvalidArguments
from .tables import PREFIX, metadata

ENV_VAR = f"{TOOL.upper()}_DATABASE_URL"
# Что значит каждая — `llm describe --json` перечисляет их (x-rb-env).
ENV_VARS = {ENV_VAR: "Общая PostgreSQL для журнала расходов; не задана → локальная SQLite (usage.path)"}
VERSION_TABLE = f"alembic_version_{TOOL}"
CONNECT_TIMEOUT_S = 5
# Сколько ждать блокировку SQLite: файл пишут несколько процессов (wp-bulk, antagor, `llm`).
SQLITE_BUSY_TIMEOUT_S = 10
# JSON (`tags`) — кириллицей, как писал журнал до v0.5.0, а не \\uXXXX.
_json = partial(json.dumps, ensure_ascii=False)


def database_url() -> str | None:
    return os.environ.get(ENV_VAR) or None


def sqlite_path() -> Path:
    """Локальная база — файл журнала из конфига (`usage.path`)."""
    from .. import config

    return config.load().usage_path()


def is_postgres(engine: sa.Engine | sa.Connection) -> bool:
    return engine.dialect.name == "postgresql"


def describe(engine: sa.Engine) -> str:
    """Куда смотрит engine, без пароля — для `db status`."""
    return engine.url.render_as_string(hide_password=True)


def _sqlite_pragmas(dbapi_connection, _record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    # WAL — режим файла, он живёт между запусками; смена режима не ждёт busy_timeout
    # и при открытом другим процессом файле сразу даёт "database is locked". Режим
    # тогда уже нужный — ошибку глотаем.
    with contextlib.suppress(Exception):
        cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()


def sqlite_engine(path: Path) -> sa.Engine:
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = sa.create_engine(
        f"sqlite:///{path}", connect_args={"timeout": SQLITE_BUSY_TIMEOUT_S}, json_serializer=_json
    )
    event.listen(engine, "connect", _sqlite_pragmas)
    return engine


def postgres_engine(url: str) -> sa.Engine:
    """Engine для `url` (любое написание `postgres://` / `postgresql://` → драйвер psycopg), соединение проверено."""
    try:
        parsed = sa.make_url(url)
    except sa_exc.ArgumentError as exc:
        raise DatabaseUnavailable(f"{ENV_VAR} — не строка подключения к базе") from exc
    if parsed.drivername.split("+")[0] not in ("postgres", "postgresql"):
        raise DatabaseUnavailable(f"{ENV_VAR}: поддерживается только PostgreSQL, не '{parsed.drivername}'")
    engine = sa.create_engine(
        parsed.set(drivername="postgresql+psycopg"),
        pool_pre_ping=True,
        json_serializer=_json,
        connect_args={"connect_timeout": CONNECT_TIMEOUT_S},
    )
    try:
        with engine.connect():
            pass
    except sa_exc.OperationalError as exc:
        engine.dispose()
        where = parsed.render_as_string(hide_password=True)
        reason = str(exc.orig).strip().splitlines()[0]  # psycopg повторяет причину для каждого адреса
        raise DatabaseUnavailable(f"не подключиться к {where}: {reason}") from exc
    return engine


def alembic_config(connection: sa.Connection | None = None) -> Config:
    config = Config()
    config.set_main_option("script_location", f"{__name__}:migrations")
    config.attributes.update(connection=connection, metadata=metadata, prefix=PREFIX, version_table=VERSION_TABLE)
    return config


def head_revision() -> str:
    head = ScriptDirectory.from_config(alembic_config()).get_current_head()
    if head is None:
        raise RuntimeError("в migrations/versions/ нет ревизий")
    return head


def current_revision(connection: sa.Connection) -> str | None:
    return MigrationContext.configure(connection, opts={"version_table": VERSION_TABLE}).get_current_revision()


@dataclass(frozen=True)
class SchemaState:
    current: str | None
    head: str

    @property
    def up_to_date(self) -> bool:
        return self.current == self.head

    @property
    def too_new(self) -> bool:
        """База на ревизии, которой нет в миграциях этой версии: её смигрировал более новый релиз."""
        if self.current is None:
            return False
        try:
            return ScriptDirectory.from_config(alembic_config()).get_revision(self.current) is None
        except (RevisionError, CommandError):  # на неизвестный id alembic бросает, а не возвращает None
            return True


def schema_state(engine: sa.Engine) -> SchemaState:
    with engine.connect() as connection:
        return SchemaState(current_revision(connection), head_revision())


def check_schema(engine: sa.Engine) -> None:
    """Ошибка, если база не ровно на последней ревизии этой версии."""
    state = schema_state(engine)
    if state.up_to_date:
        return
    if state.too_new:
        raise DatabaseTooNew(state.current or "")
    raise DatabaseNotMigrated(state.current, state.head)


def upgrade(engine: sa.Engine) -> SchemaState:
    """Применить недостающие миграции одной транзакцией.

    Два запуска сразу встают в очередь: в PostgreSQL — на advisory lock, в SQLite —
    на `BEGIN IMMEDIATE` (несколько процессов открывают один файл одновременно);
    второй видит уже смигрированную базу и ничего не делает.
    """
    state = schema_state(engine)
    if state.up_to_date:
        return state
    if state.too_new:  # никогда не «обновлять» базу до более старой ревизии
        raise DatabaseTooNew(state.current or "")
    with engine.begin() as connection:
        if is_postgres(connection):
            connection.execute(sa.text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": VERSION_TABLE})
        else:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
        command.upgrade(alembic_config(connection), "head")
    return schema_state(engine)


def open_db(path: Path | None = None, *, check: bool = True) -> sa.Engine:
    """База llmkit: `LLMKIT_DATABASE_URL`, иначе локальная SQLite (`path` или `sqlite_path()`).

    SQLite мигрируется при открытии. PostgreSQL только сверяется (`check=False`
    пропускает и это — для `db upgrade`/`db status`, которые сами показывают ревизию).
    """
    url = database_url()
    if url is None:
        engine = sqlite_engine(path or sqlite_path())
        upgrade(engine)
        return engine
    engine = postgres_engine(url)
    if check:
        try:
            check_schema(engine)
        except Exception:
            engine.dispose()
            raise
    return engine


def import_sqlite(source: Path, target: sa.Engine, *, dry_run: bool = False) -> dict[str, int]:
    """Скопировать таблицы llmkit из локального файла SQLite в `target` (общую базу) одной транзакцией.

    Источник сначала приводится к последней ревизии (своими миграциями, как при любом
    открытии — даже при `dry_run`), так что таблицы с обеих сторон одинаковые. Каждая
    таблица в `target` должна быть пустой: импорт — разовый переезд, не слияние.
    Возвращает число строк по таблицам.
    """
    if not source.is_file():
        raise InvalidArguments(f"нет базы SQLite: '{source}'")
    if target.url.database and Path(target.url.database).resolve() == source.resolve():
        raise InvalidArguments("источник и цель — одна и та же база")
    source_engine = sqlite_engine(source)
    try:
        upgrade(source_engine)
        check_schema(target)
        counts: dict[str, int] = {}
        with source_engine.connect() as src, target.begin() as dst:
            for table in metadata.sorted_tables:  # родители раньше детей (внешние ключи)
                if dst.execute(sa.select(sa.func.count()).select_from(table)).scalar_one():
                    raise InvalidArguments(f"таблица '{table.name}' в целевой базе не пуста")
                counts[table.name] = src.execute(sa.select(sa.func.count()).select_from(table)).scalar_one()
                if dry_run:
                    continue
                rows = src.execute(sa.select(table)).mappings()
                while batch := rows.fetchmany(1000):
                    dst.execute(sa.insert(table), [dict(row) for row in batch])
                if is_postgres(dst):
                    _reset_sequences(dst, table)
        return counts
    finally:
        source_engine.dispose()


def _reset_sequences(connection: sa.Connection, table: sa.Table) -> None:
    """Строки пришли со своими id: сдвинуть serial/identity за них, иначе следующая вставка столкнётся."""
    for column in table.primary_key.columns:
        if column.autoincrement is True or (column.autoincrement == "auto" and isinstance(column.type, sa.Integer)):
            top = f"SELECT max({column.name}) FROM {table.name}"  # noqa: S608 — имена из tables.py, не ввод
            connection.execute(
                sa.text(f"SELECT setval(pg_get_serial_sequence(:table, :column), coalesce(({top}), 0) + 1, false)"),
                {"table": table.name, "column": column.name},
            )


__all__ = [
    "ENV_VAR",
    "ENV_VARS",
    "PREFIX",
    "VERSION_TABLE",
    "SchemaState",
    "check_schema",
    "database_url",
    "describe",
    "import_sqlite",
    "open_db",
    "schema_state",
    "sqlite_path",
    "upgrade",
]
