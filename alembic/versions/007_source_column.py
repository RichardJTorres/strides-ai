"""Add source discriminator column to activities table.

Revision ID: 007
Revises: 006
Create Date: 2026-06-27
"""

import sqlalchemy as sa
from alembic import op

revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("activities") as batch_op:
        batch_op.add_column(sa.Column("source", sa.Text(), nullable=True))

    op.execute("UPDATE activities SET source = 'hevy' WHERE hevy_workout_id IS NOT NULL")
    op.execute("UPDATE activities SET source = 'strava' WHERE hevy_workout_id IS NULL")


def downgrade() -> None:
    with op.batch_alter_table("activities") as batch_op:
        batch_op.drop_column("source")
