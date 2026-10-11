"""The only module that knows Activity.model_dump()'s shape.

Converts raw DB rows into CardioAnalyticsActivity, dropping persistence details and validating
at the boundary so cardio.py's pure functions can trust their input completely: date is always a
real date, hr_zone_pct is either all 5 zones (finite) or None, never partial.
"""

import math
from datetime import date as date_cls

from ..activity_types import SportType
from .models import CardioAnalyticsActivity

ZONE_FIELDS = ("hr_zone_1_pct", "hr_zone_2_pct", "hr_zone_3_pct", "hr_zone_4_pct", "hr_zone_5_pct")
ZONE_LABELS = ("Z1", "Z2", "Z3", "Z4", "Z5")


def _finite_or_none(value: float | None) -> float | None:
    if value is None:
        return None
    try:
        return value if math.isfinite(value) else None
    except TypeError:
        return None


def _nonnegative_or_none(value: float | None) -> float | None:
    value = _finite_or_none(value)
    return value if value is not None and value >= 0 else None


def _hr_zone_pct(row: dict) -> dict[str, float] | None:
    values = [_finite_or_none(row.get(f)) for f in ZONE_FIELDS]
    if any(v is None or not 0 <= v <= 100 for v in values):
        return None
    if not math.isclose(sum(values), 100.0, abs_tol=0.1):
        return None
    return dict(zip(ZONE_LABELS, values))


def to_cardio_analytics(rows: list[dict]) -> list[CardioAnalyticsActivity]:
    """Convert DB rows (Activity.model_dump()) into analytics inputs, dropping unparseable rows."""
    result = []
    for row in rows:
        raw_date = row.get("date")
        try:
            parsed_date = date_cls.fromisoformat(raw_date) if raw_date else None
        except (TypeError, ValueError):
            parsed_date = None
        if parsed_date is None:
            continue

        result.append(
            CardioAnalyticsActivity(
                source=row.get("source") or "unknown",
                sport_type=SportType.from_api(row.get("sport_type")),
                date=parsed_date,
                name=row.get("name"),
                moving_time_s=_nonnegative_or_none(row.get("moving_time_s")),
                distance_m=_nonnegative_or_none(row.get("distance_m")),
                elevation_gain_m=_nonnegative_or_none(row.get("elevation_gain_m")),
                avg_pace_s_per_km=_nonnegative_or_none(row.get("avg_pace_s_per_km")),
                avg_hr=_nonnegative_or_none(row.get("avg_hr")),
                avg_cadence=_nonnegative_or_none(row.get("avg_cadence")),
                hr_zone_pct=_hr_zone_pct(row),
                cardiac_decoupling_pct=_finite_or_none(row.get("cardiac_decoupling_pct")),
                pace_fade_seconds=_finite_or_none(row.get("pace_fade_seconds")),
            )
        )
    return result
