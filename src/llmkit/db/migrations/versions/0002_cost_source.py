"""llmkit_calls.cost_source и billable; те же колонки в конце llmkit_v1_calls

Revision ID: 0002
Revises: 0001

Общая схема стоимости инструментов (T175). Колонки только добавляются (expand):
v0.9 пишет строки без них — там NULL. В представлении v1 они дописаны в конец,
прежние колонки не меняются.
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

V1_COLUMNS = (
    "id, {called_at} AS called_at, task_id, tags, level, model, served_model, provider,"
    " status, error_type, attempt, prompt_tokens, completion_tokens, cost_usd, cost_known, latency_ms"
)


def _create_view(columns: str) -> None:
    bind = op.get_bind()
    called_at = "to_timestamp(ts)" if bind.dialect.name == "postgresql" else "datetime(ts, 'unixepoch')"
    replace = "OR REPLACE " if bind.dialect.name == "postgresql" else ""
    if not replace:
        op.execute("DROP VIEW IF EXISTS llmkit_v1_calls")
    op.execute(
        f"CREATE {replace}VIEW llmkit_v1_calls AS SELECT {columns.format(called_at=called_at)} FROM llmkit_calls"  # noqa: S608 — колонки литералом выше, не ввод
    )


def upgrade() -> None:
    op.add_column("llmkit_calls", sa.Column("cost_source", sa.Text))
    op.add_column("llmkit_calls", sa.Column("billable", sa.Integer))
    _create_view(V1_COLUMNS + ", cost_source, billable")


def downgrade() -> None:
    op.execute("DROP VIEW llmkit_v1_calls")  # PostgreSQL не убирает колонки представления через REPLACE
    _create_view(V1_COLUMNS)
    with op.batch_alter_table("llmkit_calls") as batch:
        batch.drop_column("billable")
        batch.drop_column("cost_source")
