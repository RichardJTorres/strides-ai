"""Store the last two imperial analysis columns in SI units.

elevation_per_mile (ft/mi) -> climb_m_per_km (m/km)
pace_fade_seconds  (s/mi)  -> pace_fade_s_per_km (s/km)

Every stored measurement is now SI; display conversion lives in strides_ai/units.py.
"""

import sqlalchemy as sa
from alembic import op

revision = "011"
down_revision = "010"
branch_labels = None
depends_on = None

KM_PER_MILE = 1.609344
FEET_PER_METER = 3.28084
# ft/mi -> m/km
FT_PER_MI_TO_M_PER_KM = 1 / (FEET_PER_METER * KM_PER_MILE)


def upgrade():
    with op.batch_alter_table("activities") as batch:
        batch.alter_column("elevation_per_mile", new_column_name="climb_m_per_km")
        batch.alter_column("pace_fade_seconds", new_column_name="pace_fade_s_per_km")
    op.execute(
        sa.text(
            "UPDATE activities SET "
            "climb_m_per_km = climb_m_per_km * :climb, "
            "pace_fade_s_per_km = pace_fade_s_per_km / :km_per_mi"
        ).bindparams(climb=FT_PER_MI_TO_M_PER_KM, km_per_mi=KM_PER_MILE)
    )


def downgrade():
    op.execute(
        sa.text(
            "UPDATE activities SET "
            "climb_m_per_km = climb_m_per_km / :climb, "
            "pace_fade_s_per_km = pace_fade_s_per_km * :km_per_mi"
        ).bindparams(climb=FT_PER_MI_TO_M_PER_KM, km_per_mi=KM_PER_MILE)
    )
    with op.batch_alter_table("activities") as batch:
        batch.alter_column("climb_m_per_km", new_column_name="elevation_per_mile")
        batch.alter_column("pace_fade_s_per_km", new_column_name="pace_fade_seconds")
