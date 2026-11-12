"""Turn the legacy calendar_prefs.races list into planned race workouts.

Race-type workouts are now the only source of races. The column stays, emptied and unread.
See strides_ai/races_migrate.py.
"""

from alembic import op

from strides_ai.races_migrate import migrate_races

revision = "014"
down_revision = "013"
branch_labels = None
depends_on = None


def upgrade():
    migrate_races(op.get_bind())


def downgrade():
    # Race workouts stay in the plan; nothing to restore.
    pass
