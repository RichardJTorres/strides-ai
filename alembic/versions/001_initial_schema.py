"""Initial schema — all 7 tables.

Revision ID: 001
Revises:
Create Date: 2026-03-08
"""

import sqlalchemy as sa
from alembic import op

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "activities",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("date", sa.Text(), nullable=True),
        sa.Column("distance_m", sa.Float(), nullable=True),
        sa.Column("moving_time_s", sa.Integer(), nullable=True),
        sa.Column("elapsed_time_s", sa.Integer(), nullable=True),
        sa.Column("elevation_gain_m", sa.Float(), nullable=True),
        sa.Column("avg_pace_s_per_km", sa.Float(), nullable=True),
        sa.Column("avg_hr", sa.Float(), nullable=True),
        sa.Column("max_hr", sa.Integer(), nullable=True),
        sa.Column("avg_cadence", sa.Float(), nullable=True),
        sa.Column("suffer_score", sa.Integer(), nullable=True),
        sa.Column("perceived_exertion", sa.Float(), nullable=True),
        sa.Column("sport_type", sa.Text(), nullable=True),
        sa.Column("raw_json", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "conversations",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("mode", sa.Text(), nullable=False, server_default="running"),
        sa.Column("model", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.Text(),
            nullable=True,
            server_default=sa.text("datetime('now')"),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "memories",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False, unique=True),
        sa.Column(
            "created_at",
            sa.Text(),
            nullable=True,
            server_default=sa.text("datetime('now')"),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "settings",
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )
    op.create_table(
        "profiles",
        sa.Column("mode", sa.Text(), nullable=False),
        sa.Column("fields_json", sa.Text(), nullable=False),
        sa.Column(
            "updated_at",
            sa.Text(),
            nullable=True,
            server_default=sa.text("datetime('now')"),
        ),
        sa.PrimaryKeyConstraint("mode"),
    )
    op.create_table(
        "calendar_prefs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("rest_days", sa.Text(), nullable=False, server_default="'[]'"),
        sa.Column("long_run_days", sa.Text(), nullable=False, server_default="'[]'"),
        sa.Column("frequency", sa.Integer(), nullable=False, server_default="4"),
        sa.Column("blocked_days", sa.Text(), nullable=False, server_default="'[]'"),
        sa.Column("races", sa.Text(), nullable=False, server_default="'[]'"),
        sa.CheckConstraint("id = 1"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "training_plan",
        sa.Column("date", sa.Text(), nullable=False),
        sa.Column("workout_type", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("distance_km", sa.Float(), nullable=True),
        sa.Column("elevation_m", sa.Float(), nullable=True),
        sa.Column("duration_min", sa.Integer(), nullable=True),
        sa.Column("intensity", sa.Text(), nullable=True),
        sa.Column("nutrition_json", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.Text(),
            nullable=True,
            server_default=sa.text("datetime('now')"),
        ),
        sa.PrimaryKeyConstraint("date"),
    )


def downgrade() -> None:
    op.drop_table("training_plan")
    op.drop_table("calendar_prefs")
    op.drop_table("profiles")
    op.drop_table("settings")
    op.drop_table("memories")
    op.drop_table("conversations")
    op.drop_table("activities")
