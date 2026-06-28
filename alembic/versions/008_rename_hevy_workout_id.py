"""Rename hevy_workout_id to external_id on the activities table.

Revision ID: 008
Revises: 007
Create Date: 2026-06-27
"""

import sqlalchemy as sa
from alembic import op

revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("activities") as batch_op:
        batch_op.alter_column("hevy_workout_id", new_column_name="external_id")


def downgrade() -> None:
    with op.batch_alter_table("activities") as batch_op:
        batch_op.alter_column("external_id", new_column_name="hevy_workout_id")
