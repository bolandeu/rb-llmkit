"""llmkit_calls и представление llmkit_v1_calls

Revision ID: 0001
Revises:

Локальная SQLite до v0.5.0 уже содержит журнал в таблице `calls` (usage.sqlite):
он переименовывается в `llmkit_calls` вместе со строками; базы до v0.4.2 получают
колонку `served_model`. В новой базе (и в PostgreSQL) таблица создаётся.

Имена литералами намеренно: миграция — история и не должна меняться вместе с
кодом, который она могла бы импортировать.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if bind.dialect.name == "sqlite" and inspector.has_table("calls"):
        if "served_model" not in {column["name"] for column in inspector.get_columns("calls")}:
            op.add_column("calls", sa.Column("served_model", sa.Text))
        op.execute("DROP INDEX IF EXISTS calls_ts")
        op.execute("DROP INDEX IF EXISTS calls_status")
        op.rename_table("calls", "llmkit_calls")
    else:
        op.create_table(
            "llmkit_calls",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("ts", sa.Float),
            sa.Column("task_id", sa.Text),
            sa.Column("tags", sa.JSON().with_variant(postgresql.JSONB(), "postgresql")),
            sa.Column("level", sa.Text),
            sa.Column("model", sa.Text),
            sa.Column("provider", sa.Text),
            sa.Column("status", sa.Text),
            sa.Column("error_type", sa.Text),
            sa.Column("attempt", sa.Integer),
            sa.Column("prompt_tokens", sa.Integer),
            sa.Column("completion_tokens", sa.Integer),
            sa.Column("cost_usd", sa.Float),
            sa.Column("cost_known", sa.Integer),
            sa.Column("latency_ms", sa.Integer),
            sa.Column("pid", sa.Integer),
            sa.Column("served_model", sa.Text),
            sa.PrimaryKeyConstraint("id", name="llmkit_calls_pk"),
        )
    op.create_index("llmkit_calls_ts_ix", "llmkit_calls", ["ts"])
    op.create_index("llmkit_calls_status_ix", "llmkit_calls", ["status"])
    # Контракт с другими инструментами: они читают представление, не таблицу. Его
    # колонки не меняются — другая форма будет новым представлением `_v2_` рядом.
    called_at = "to_timestamp(ts)" if bind.dialect.name == "postgresql" else "datetime(ts, 'unixepoch')"
    op.execute(
        f"""
        CREATE VIEW llmkit_v1_calls AS
        SELECT id, {called_at} AS called_at, task_id, tags, level, model, served_model, provider,
               status, error_type, attempt, prompt_tokens, completion_tokens, cost_usd, cost_known, latency_ms
        FROM llmkit_calls
        """  # noqa: S608 — выражение выбрано выше, не ввод
    )


def downgrade() -> None:
    op.execute("DROP VIEW llmkit_v1_calls")
    op.drop_table("llmkit_calls")
