"""Add avg_rpe column to activities.

Revision ID: 007
Revises: 006
Create Date: 2026-05-14
"""

import sqlalchemy as sa
from alembic import op

revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("activities") as batch_op:
        batch_op.add_column(sa.Column("avg_rpe", sa.Float(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("activities") as batch_op:
        batch_op.drop_column("avg_rpe")
