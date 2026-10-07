"""Add RideWithGPS route fields to training_plan table.

Revision ID: 009
Revises: 008
Create Date: 2026-10-06
"""

import sqlalchemy as sa
from alembic import op

revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("training_plan") as batch_op:
        batch_op.add_column(sa.Column("route_url", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("route_analysis_json", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("route_analyzed_at", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("route_analysis_model", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("training_plan") as batch_op:
        batch_op.drop_column("route_analysis_model")
        batch_op.drop_column("route_analyzed_at")
        batch_op.drop_column("route_analysis_json")
        batch_op.drop_column("route_url")
