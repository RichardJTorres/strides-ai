"""LLM usage log: one row per model call (chat turns and one-shot analyses).

Token columns are nullable; NULL means the provider did not report that figure.
"""

import sqlalchemy as sa
from alembic import op

revision = "019"
down_revision = "018"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "llm_usage",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("ts", sa.Text, server_default=sa.text("datetime('now')")),
        sa.Column("source", sa.Text, nullable=False),
        sa.Column("provider", sa.Text, nullable=False),
        sa.Column("model", sa.Text, nullable=False),
        sa.Column("mode", sa.Text, nullable=True),
        sa.Column("turn_id", sa.Integer, nullable=True),
        sa.Column("input_total", sa.Integer, nullable=True),
        sa.Column("cache_read", sa.Integer, nullable=True),
        sa.Column("cache_write", sa.Integer, nullable=True),
        sa.Column("output_total", sa.Integer, nullable=True),
        sa.Column("reasoning", sa.Integer, nullable=True),
    )
    op.create_index("ix_llm_usage_ts", "llm_usage", ["ts"])


def downgrade():
    op.drop_index("ix_llm_usage_ts", table_name="llm_usage")
    op.drop_table("llm_usage")
