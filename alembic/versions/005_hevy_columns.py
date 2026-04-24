"""Add HEVY-specific columns to activities table.

Revision ID: 005
Revises: 004
Create Date: 2026-04-24
"""

import sqlalchemy as sa
from alembic import op

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("activities") as batch_op:
        batch_op.add_column(sa.Column("hevy_workout_id", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("exercises_json", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("total_volume_kg", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("total_sets", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("activities") as batch_op:
        batch_op.drop_column("total_sets")
        batch_op.drop_column("total_volume_kg")
        batch_op.drop_column("exercises_json")
        batch_op.drop_column("hevy_workout_id")
