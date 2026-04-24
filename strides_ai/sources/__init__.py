"""Data source registry.

Each DataSource encapsulates one external data provider (Strava, HEVY).
Use ``get_source_for_activity`` to resolve which source owns a given activity.
"""

from ..db.models import LIFT_TYPES
from .hevy import HevySource
from .strava import StravaSource

strava_source = StravaSource()
hevy_source = HevySource()


def get_source_for_activity(activity) -> StravaSource | HevySource:
    """Return the DataSource responsible for the given activity's sport type."""
    if activity.sport_type in LIFT_TYPES:
        return hevy_source
    return strava_source
