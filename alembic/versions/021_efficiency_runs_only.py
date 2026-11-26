"""Score effort efficiency on runs that are not hilly, and only against each other.

Pace per heartbeat is not a fitness signal on a ride (grade, wind and drafting set speed) or on
a hilly course (terrain sets pace), and the old min-max scale mixed every sport, so rides
stretched it and pushed run scores down. Clear the score where it is not valid and rescale the
rest over the valid rows only. Raw values stay stored. Frozen SQL on purpose; after this,
`db.activities.renormalize_effort_efficiency` applies the same rule after every sync.
"""

from alembic import op

revision = "021"
down_revision = "020"
branch_labels = None
depends_on = None

RIDES = "('Ride', 'VirtualRide', 'GravelRide')"
# 100 ft/mi in m/km, as decoupling.HIGH_CLIMB_M_PER_KM is today (frozen here).
HIGH_CLIMB_M_PER_KM = 100 / (3.28084 * 1.609344)


def _valid(t: str) -> str:
    """SQL for decoupling.efficiency_validity at the time of writing: not a ride (a NULL sport
    is not a ride) and not hilly, where the climb ratio is the stored one or, for rows analysed
    before it was stored, derived from the summary; no ratio at all is not hilly."""
    climb = (
        f"COALESCE({t}.climb_m_per_km, CASE WHEN {t}.distance_m > 0 AND {t}.elevation_gain_m"
        f" IS NOT NULL THEN {t}.elevation_gain_m / ({t}.distance_m / 1000.0) END)"
    )
    return (
        f"{t}.effort_efficiency_raw IS NOT NULL AND COALESCE({t}.sport_type, '') NOT IN {RIDES}"
        f" AND ({climb} IS NULL OR {climb} <= {HIGH_CLIMB_M_PER_KM!r})"
    )


def upgrade():
    op.execute(
        "UPDATE activities SET effort_efficiency_score = NULL"
        f" WHERE effort_efficiency_raw IS NOT NULL AND NOT ({_valid('activities')})"
    )
    op.execute(
        "UPDATE activities SET effort_efficiency_score = ("
        "  SELECT CASE WHEN MAX(v.effort_efficiency_raw) = MIN(v.effort_efficiency_raw) THEN 50.0"
        "  ELSE ROUND(100.0 * (MAX(v.effort_efficiency_raw) - activities.effort_efficiency_raw)"
        "             / (MAX(v.effort_efficiency_raw) - MIN(v.effort_efficiency_raw)), 2) END"
        f"  FROM activities v WHERE {_valid('v')}"
        f") WHERE {_valid('activities')}"
    )
    # Cached Insights reports may cite the old figures; DIGEST_VERSION also invalidates them.
    op.execute("DELETE FROM settings WHERE key LIKE 'charts_insights:%'")


def downgrade():
    pass  # the old cross-sport scores are recomputable only by re-analysis
