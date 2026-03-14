"""Add run analysis columns to activities table.

Revision ID: 002
Revises: 001
Create Date: 2026-03-14
"""

import sqlalchemy as sa
from alembic import op

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("activities") as batch_op:
        batch_op.add_column(sa.Column("cardiac_decoupling_pct", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("hr_zone_1_pct", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("hr_zone_2_pct", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("hr_zone_3_pct", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("hr_zone_4_pct", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("hr_zone_5_pct", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("pace_fade_seconds", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("cadence_std_dev", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("effort_efficiency_raw", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("effort_efficiency_score", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("elevation_per_mile", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("high_elevation_flag", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("suffer_score_mismatch_flag", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("analysis_summary", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("deep_dive_report", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("deep_dive_completed_at", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("analysis_status", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("activities") as batch_op:
        batch_op.drop_column("analysis_status")
        batch_op.drop_column("deep_dive_completed_at")
        batch_op.drop_column("deep_dive_report")
        batch_op.drop_column("analysis_summary")
        batch_op.drop_column("suffer_score_mismatch_flag")
        batch_op.drop_column("high_elevation_flag")
        batch_op.drop_column("elevation_per_mile")
        batch_op.drop_column("effort_efficiency_score")
        batch_op.drop_column("effort_efficiency_raw")
        batch_op.drop_column("cadence_std_dev")
        batch_op.drop_column("pace_fade_seconds")
        batch_op.drop_column("hr_zone_5_pct")
        batch_op.drop_column("hr_zone_4_pct")
        batch_op.drop_column("hr_zone_3_pct")
        batch_op.drop_column("hr_zone_2_pct")
        batch_op.drop_column("hr_zone_1_pct")
        batch_op.drop_column("cardiac_decoupling_pct")
