"""chat_turns: durable lifecycle of each chat turn (status, partial text, events)."""

import sqlalchemy as sa
from alembic import op

revision = "016"
down_revision = "015"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "chat_turns",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("mode", sa.String, nullable=False),
        sa.Column("status", sa.String, nullable=False, server_default="running"),
        sa.Column("user_message_id", sa.Integer),
        sa.Column("assistant_message_id", sa.Integer),
        sa.Column("partial_text", sa.Text, nullable=False, server_default=""),
        sa.Column("events_json", sa.Text, nullable=False, server_default="{}"),
        sa.Column("delivered", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("started_at", sa.Text, server_default=sa.text("datetime('now')")),
        sa.Column("updated_at", sa.Text, server_default=sa.text("datetime('now')")),
    )
    op.create_index("ix_chat_turns_mode_id", "chat_turns", ["mode", "id"])


def downgrade():
    op.drop_index("ix_chat_turns_mode_id", "chat_turns")
    op.drop_table("chat_turns")
