"""Таблицы llmkit (SQLAlchemy Core) — зеркало последней миграции (`migrations/versions/`).

Все имена начинаются с `PREFIX` (`llmkit_`): в общей PostgreSQL таблицы всех
инструментов (и Directus) лежат в одной схеме `public`. Меняя таблицу здесь,
добавьте миграцию руками — tests/test_db.py падает, если схема после миграций
и эти метаданные расходятся.

У каждой таблицы `info={"kind": "data"}` (результат инструмента, при удалении
теряется) или `"cache"` (копия того, что можно получить заново); без него
tests/test_db.py падает. `llm describe --json` публикует это (x-rb-data).
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
    info={"kind": "data"},
)

# Представления `llmkit_v1_*`, которые читают другие инструменты, Directus и
# платформа вместо таблиц, — контракт данных, его публикует `llm describe --json`
# (x-rb-data.views). Создаёт их миграция (`CREATE VIEW`), здесь — объявление;
# tests/test_db.py падает, если представления нет в базе после миграций или
# колонки расходятся. Колонки не меняются: другая форма — новое `_v2_` рядом.
# Отдельные метаданные: `metadata` — зеркало только таблиц.
views = sa.MetaData()

v1_calls = sa.Table(
    f"{PREFIX}v1_calls",
    views,
    sa.Column("id", sa.Integer, comment="Номер попытки в журнале"),
    sa.Column("called_at", sa.DateTime(timezone=True), comment="Когда сделан вызов (UTC)"),
    sa.Column("task_id", sa.Text, comment="Id задачи: попытки одного вызова по цепочке моделей"),
    sa.Column("tags", sa.JSON, comment='Метки вызывающего для учёта расходов: {"метка": "значение"}'),
    sa.Column("level", sa.Text, comment="Уровень цепочки моделей из конфига (cheap, judge…)"),
    sa.Column("model", sa.Text, comment="Запрошенная модель: провайдер/модель"),
    sa.Column("served_model", sa.Text, comment="Модель, которую назвал провайдер в ответе"),
    sa.Column("provider", sa.Text, comment="Провайдер из конфига"),
    sa.Column("status", sa.Text, comment="Итог попытки: ok, failed или cache (ответ из кэша)"),
    sa.Column("error_type", sa.Text, comment="Класс ошибки, если попытка упала"),
    sa.Column("attempt", sa.Integer, comment="Номер повтора на этой модели (0 — первая попытка или кэш)"),
    sa.Column("prompt_tokens", sa.Integer, comment="Токены запроса"),
    sa.Column("completion_tokens", sa.Integer, comment="Токены ответа"),
    sa.Column("cost_usd", sa.Float, comment="Стоимость, USD"),
    sa.Column("cost_known", sa.Integer, comment="1 — стоимость известна, 0 — цены нет"),
    sa.Column("latency_ms", sa.Integer, comment="Длительность вызова, мс"),
    comment="Журнал вызовов LLM: одна строка на попытку",
)
