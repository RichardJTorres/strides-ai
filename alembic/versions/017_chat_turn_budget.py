"""chat_turns.budget_json: per-turn record of what was sent, timings and the stop reason."""

import sqlalchemy as sa
from alembic import op

revision = "017"
down_revision = "016"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("chat_turns", sa.Column("budget_json", sa.Text, nullable=True))


def downgrade():
    with op.batch_alter_table("chat_turns") as batch:
        batch.drop_column("budget_json")
