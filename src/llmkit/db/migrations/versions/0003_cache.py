"""llmkit_cache: кэш ответов в базе журнала

Revision ID: 0003
Revises: 0002

Таблица только добавляется (expand): прежний релиз её не трогает.
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "llmkit_cache",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("key", sa.Text, nullable=False),
        sa.Column("model", sa.Text),
        sa.Column("created_at", sa.Float),
        sa.Column("response", sa.Text),
        sa.PrimaryKeyConstraint("id", name="llmkit_cache_pk"),
        sa.UniqueConstraint("key", name="llmkit_cache_key_uq"),
    )
    op.create_index("llmkit_cache_created_at_ix", "llmkit_cache", ["created_at"])


def downgrade() -> None:
    op.drop_index("llmkit_cache_created_at_ix", "llmkit_cache")
    op.drop_table("llmkit_cache")
