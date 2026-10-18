"""Unify the per-mode athlete profiles into one shared profile.

Legacy rows (personal, running, cycling, hybrid, lifting) are merged into
shared / running / cycling / lifting and kept as legacy:<name> for rollback.
See strides_ai/profile_migrate.py.
"""

from alembic import op

from strides_ai.profile_migrate import migrate_profile_rows

revision = "012"
down_revision = "011"
branch_labels = None
depends_on = None


def upgrade():
    migrate_profile_rows(op.get_bind())


def downgrade():
    # Legacy rows were preserved under legacy:<name>; restore them and drop the new layout.
    conn = op.get_bind()
    conn.exec_driver_sql(
        "DELETE FROM profiles WHERE mode IN ('shared','running','cycling','lifting')"
    )
    conn.exec_driver_sql("UPDATE profiles SET mode = substr(mode, 8) WHERE mode LIKE 'legacy:%'")
