"""Unit tests for strides_ai.analytics.aggregation."""

from datetime import date

import pytest

from strides_ai.analytics.aggregation import (
    monday_of,
    pace_fade_to_unit,
    to_distance_unit,
    to_elevation_unit,
    to_hours,
    to_pace_unit,
    trailing_date_rolling_avg,
    trailing_weekly_rolling_avg,
    week_range,
)

# ── monday_of / week_range ──────────────────────────────────────────────────────


def test_monday_of_already_monday():
    assert monday_of(date(2026, 1, 5)) == date(2026, 1, 5)  # a Monday


def test_monday_of_midweek():
    assert monday_of(date(2026, 1, 8)) == date(2026, 1, 5)  # Thursday -> that Monday


def test_week_range_single_week():
    assert week_range(date(2026, 1, 5), date(2026, 1, 8)) == [date(2026, 1, 5)]


def test_week_range_fills_zero_weeks():
    weeks = week_range(date(2026, 1, 5), date(2026, 1, 19))
    assert weeks == [date(2026, 1, 5), date(2026, 1, 12), date(2026, 1, 19)]


# ── trailing_weekly_rolling_avg ──────────────────────────────────────────────────


def test_trailing_weekly_rolling_avg_single_week_equals_itself():
    weeks = [date(2026, 1, 5)]
    result = trailing_weekly_rolling_avg(weeks, {date(2026, 1, 5): 10.0}, window=4)
    assert result[date(2026, 1, 5)] == 10.0


def test_trailing_weekly_rolling_avg_zero_fills_missing_weeks():
    weeks = [date(2026, 1, 5), date(2026, 1, 12)]
    values = {date(2026, 1, 5): 10.0}  # second week has no entry
    result = trailing_weekly_rolling_avg(weeks, values, window=4)
    assert result[date(2026, 1, 12)] == pytest.approx(5.0)  # (10 + 0) / 2


def test_trailing_weekly_rolling_avg_window_caps_at_available_weeks():
    weeks = [date(2026, 1, 5), date(2026, 1, 12), date(2026, 1, 19)]
    values = {w: 10.0 for w in weeks}
    result = trailing_weekly_rolling_avg(weeks, values, window=4)
    # only 3 weeks exist even though window=4 — average over what's available
    assert result[date(2026, 1, 19)] == pytest.approx(10.0)


# ── trailing_date_rolling_avg ─────────────────────────────────────────────────────


def test_trailing_date_rolling_avg_single_point():
    points = [(date(2026, 1, 1), 5.0)]
    assert trailing_date_rolling_avg(points, window_days=28) == [5.0]


def test_trailing_date_rolling_avg_excludes_points_outside_window():
    points = [(date(2026, 1, 1), 10.0), (date(2026, 3, 1), 20.0)]  # far apart
    result = trailing_date_rolling_avg(points, window_days=28)
    # second point's window doesn't include the first (>28 days apart)
    assert result[1] == pytest.approx(20.0)


def test_trailing_date_rolling_avg_includes_points_within_window():
    points = [(date(2026, 1, 1), 10.0), (date(2026, 1, 10), 20.0)]
    result = trailing_date_rolling_avg(points, window_days=28)
    assert result[1] == pytest.approx(15.0)


# ── unit conversion ──────────────────────────────────────────────────────────────


def test_to_distance_unit_km():
    assert to_distance_unit(1000.0, "km") == pytest.approx(1.0)


def test_to_distance_unit_miles():
    assert to_distance_unit(1609.34, "miles") == pytest.approx(1.0, rel=1e-3)


def test_to_distance_unit_none_is_zero():
    assert to_distance_unit(None, "km") == 0.0


def test_to_pace_unit_km_identity():
    assert to_pace_unit(300.0, "km") == pytest.approx(300.0)


def test_to_pace_unit_miles_converts():
    assert to_pace_unit(300.0, "miles") == pytest.approx(300.0 * 1.60934)


def test_to_hours_converts_seconds():
    assert to_hours(3600.0) == pytest.approx(1.0)


def test_to_hours_none_is_zero():
    assert to_hours(None) == 0.0


def test_to_elevation_unit_miles_converts_to_feet():
    assert to_elevation_unit(100.0, "miles") == pytest.approx(328.084, rel=1e-3)


def test_to_elevation_unit_km_stays_meters():
    assert to_elevation_unit(100.0, "km") == pytest.approx(100.0)


def test_to_elevation_unit_none_is_zero():
    assert to_elevation_unit(None, "miles") == 0.0


def test_pace_fade_to_unit_miles_identity():
    assert pace_fade_to_unit(60.0, "miles") == pytest.approx(60.0)


def test_pace_fade_to_unit_km_converts():
    # at fixed pace fade, converting from per-mile to per-km reduces the magnitude
    assert pace_fade_to_unit(60.0, "km") == pytest.approx(60.0 / 1.60934)


def test_date_rolling_average_matches_reference_with_duplicate_dates_and_gaps():
    from datetime import timedelta
    import random

    rng = random.Random(42)
    points = sorted(
        (date(2026, 1, 1) + timedelta(days=rng.randrange(120)), rng.uniform(-20, 100))
        for _ in range(250)
    )
    expected = []
    for d, _ in points:
        values = [v for pd, v in points if d - timedelta(days=27) <= pd <= d]
        expected.append(sum(values) / len(values))
    assert trailing_date_rolling_avg(points, 28) == pytest.approx(expected)


def test_date_rolling_average_includes_all_same_day_activities():
    points = [(date(2026, 1, 1), 10.0), (date(2026, 1, 1), 30.0)]
    assert trailing_date_rolling_avg(points, 28) == [20.0, 20.0]


@pytest.mark.parametrize("window", [0, -1])
def test_rolling_windows_must_be_positive(window):
    with pytest.raises(ValueError):
        trailing_date_rolling_avg([], window)
    with pytest.raises(ValueError):
        trailing_weekly_rolling_avg([], {}, window)
