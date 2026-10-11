"""Shared, metric-agnostic mechanics: weekly bucketing, rolling windows, unit conversion.

Metric-specific qualification rules (e.g. "HR must be 120-155", "cadence must be > 0") belong in
cardio.py, not here — this module only knows about dates, numbers, and units.
"""

from datetime import date, timedelta

M_TO_MI = 0.000621371
M_TO_KM = 0.001
M_TO_FT = 3.28084
KM_TO_MI_FACTOR = 1.60934


def monday_of(d: date) -> date:
    return d - timedelta(days=d.weekday())


def week_range(start: date, end: date) -> list[date]:
    """Every Monday from start's week through end's week, inclusive."""
    w = monday_of(start)
    end_week = monday_of(end)
    weeks = []
    while w <= end_week:
        weeks.append(w)
        w += timedelta(weeks=1)
    return weeks


def trailing_weekly_rolling_avg(
    weeks: list[date], values: dict[date, float], window: int
) -> dict[date, float]:
    """Trailing N-week average (including the current week), zero-filling weeks with no data."""
    if window < 1:
        raise ValueError("window must be positive")
    result: dict[date, float] = {}
    for i, w in enumerate(weeks):
        window_weeks = weeks[max(0, i - window + 1) : i + 1]
        vals = [values.get(ww, 0.0) for ww in window_weeks]
        result[w] = sum(vals) / len(vals) if vals else 0.0
    return result


def trailing_date_rolling_avg(points: list[tuple[date, float]], window_days: int) -> list[float]:
    """For each point (must be pre-sorted ascending by date), the average of all points whose
    date falls within the trailing window_days-day span ending at that point's date, inclusive."""
    if window_days < 1:
        raise ValueError("window_days must be positive")
    result = []
    left = right = 0
    total = 0.0
    # Include every activity on the endpoint date, even those later in the list. This keeps
    # same-day activities' averages identical and matches the original date-based semantics.
    for d, _ in points:
        while right < len(points) and points[right][0] <= d:
            total += points[right][1]
            right += 1
        window_start = d - timedelta(days=window_days - 1)
        while left < right and points[left][0] < window_start:
            total -= points[left][1]
            left += 1
        result.append(total / (right - left))
    return result


def to_distance_unit(meters: float | None, unit: str) -> float:
    return (meters or 0.0) * (M_TO_MI if unit == "miles" else M_TO_KM)


def to_pace_unit(s_per_km: float, unit: str) -> float:
    """Convert s/km -> s/unit."""
    return s_per_km * (KM_TO_MI_FACTOR if unit == "miles" else 1.0)


def to_hours(seconds: float | None) -> float:
    return (seconds or 0.0) / 3600.0


def to_elevation_unit(meters: float | None, unit: str) -> float:
    """Feet when unit == 'miles' (matches the existing ft/mile convention in analysis.py's
    elevation-per-mile metric), meters when unit == 'km'."""
    if meters is None:
        return 0.0
    return meters * M_TO_FT if unit == "miles" else meters


def pace_fade_to_unit(sec_per_mile: float, unit: str) -> float:
    """pace_fade_seconds is stored as sec/mile, fixed by the analysis pipeline (CLAUDE.md).
    Convert to sec/unit to match the page's distance-unit toggle."""
    return sec_per_mile if unit == "miles" else sec_per_mile / KM_TO_MI_FACTOR
