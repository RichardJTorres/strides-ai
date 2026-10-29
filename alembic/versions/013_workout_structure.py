"""Add structured-workout storage to planned workouts."""

import sqlalchemy as sa
from alembic import op

revision = "013"
down_revision = "012"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("training_plan") as batch:
        batch.add_column(sa.Column("structure_json", sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table("training_plan") as batch:
        batch.drop_column("structure_json")
