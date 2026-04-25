"""Add exercise_templates table for cached HEVY template metadata.

Revision ID: 006
Revises: 005
Create Date: 2026-04-24
"""

import sqlalchemy as sa
from alembic import op

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "exercise_templates",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("type", sa.Text(), nullable=True),
        sa.Column("primary_muscle_group", sa.Text(), nullable=True),
        sa.Column("secondary_muscle_groups", sa.Text(), nullable=True),
        sa.Column("is_custom", sa.Integer(), nullable=True),
        sa.Column(
            "updated_at",
            sa.Text(),
            nullable=True,
            server_default=sa.text("datetime('now')"),
        ),
    )


def downgrade() -> None:
    op.drop_table("exercise_templates")
