"""Add deep_dive_model column to activities table.

Revision ID: 004
Revises: 003
Create Date: 2026-03-14
"""

import sqlalchemy as sa
from alembic import op

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("activities") as batch_op:
        batch_op.add_column(sa.Column("deep_dive_model", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("activities") as batch_op:
        batch_op.drop_column("deep_dive_model")
