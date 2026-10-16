"""Add dated coaching memory states, preserving legacy memories."""

import sqlalchemy as sa
from alembic import op

revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("memories") as batch:
        batch.add_column(sa.Column("status", sa.Text(), nullable=False, server_default="current"))
        batch.add_column(sa.Column("topic", sa.Text(), nullable=True))
        batch.add_column(sa.Column("effective_from", sa.Text(), nullable=True))
        batch.add_column(sa.Column("effective_until", sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table("memories") as batch:
        for name in ("effective_until", "effective_from", "topic", "status"):
            batch.drop_column(name)
