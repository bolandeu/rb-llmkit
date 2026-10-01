"""Таблицы llmkit (SQLAlchemy Core) — зеркало последней миграции (`migrations/versions/`).

Все имена начинаются с `PREFIX` (`llmkit_`): в общей PostgreSQL таблицы всех
инструментов (и Directus) лежат в одной схеме `public`. Меняя таблицу здесь,
добавьте миграцию руками — tests/test_db.py падает, если схема после миграций
и эти метаданные расходятся.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from .._distribution import TOOL

PREFIX = f"{TOOL}_"

# Детерминированные имена ограничений: поздняя миграция удалит или изменит их по
# имени и в PostgreSQL, и в SQLite (batch mode); начинаются с имени таблицы.
metadata = sa.MetaData(
    naming_convention={
        "ix": "%(table_name)s_%(column_0_N_name)s_ix",
        "uq": "%(table_name)s_%(column_0_N_name)s_uq",
        "ck": "%(table_name)s_%(constraint_name)s_ck",
        "fk": "%(table_name)s_%(column_0_name)s_fk",
        "pk": "%(table_name)s_pk",
    }
)

# Журнал вызовов: одна строка на попытку (usage.py). Типы — как у прежней таблицы
# `calls`, чтобы её строки переехали без преобразований.
calls = sa.Table(
    f"{PREFIX}calls",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("ts", sa.Float, index=True),  # unix-время
    sa.Column("task_id", sa.Text),
    sa.Column("tags", sa.JSON().with_variant(postgresql.JSONB(), "postgresql")),  # {"метка": "значение"}
    sa.Column("level", sa.Text),
    sa.Column("model", sa.Text),
    sa.Column("provider", sa.Text),
    sa.Column("status", sa.Text, index=True),
    sa.Column("error_type", sa.Text),
    sa.Column("attempt", sa.Integer),
    sa.Column("prompt_tokens", sa.Integer),
    sa.Column("completion_tokens", sa.Integer),
    sa.Column("cost_usd", sa.Float),
    sa.Column("cost_known", sa.Integer),
    sa.Column("latency_ms", sa.Integer),
    sa.Column("pid", sa.Integer),
    sa.Column("served_model", sa.Text),
)
