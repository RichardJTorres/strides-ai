"""Null cardiac decoupling on hilly activities.

Decoupling is no longer computed when the course is flagged hilly (terrain skews the
half-vs-half split). Clear stored values for already-analyzed hilly activities; no Strava
calls are needed, and re-analysis would reproduce NULL.
"""

from alembic import op

revision = "020"
down_revision = "019"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("UPDATE activities SET cardiac_decoupling_pct = NULL WHERE high_elevation_flag = 1")
    # Cached Insights reports may cite the old decoupling figures; they regenerate on demand.
    op.execute("DELETE FROM settings WHERE key LIKE 'charts_insights:%'")


def downgrade():
    pass  # the old values are recomputable only by re-analysis
