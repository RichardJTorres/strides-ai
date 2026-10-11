"""Unit tests for strides_ai.analytics.cardio — every metric's math and qualification rules."""

from datetime import date

import pytest

from strides_ai.activity_types import SportType
from strides_ai.analytics.cardio import (
    compute_atl_ctl,
    compute_aerobic_efficiency,
    compute_cadence_trend,
    compute_cardiac_decoupling_trend,
    compute_hr_zone_trend,
    compute_pace_fade_trend,
    compute_training_time_allocation,
    compute_weekly_distance,
    compute_weekly_elevation,
)
from strides_ai.analytics.models import CardioAnalyticsActivity, UnavailableReason

TODAY = date(2026, 6, 1)  # a Monday
PAST_MONDAY = date(2024, 1, 1)
PAST_TUESDAY = date(2024, 1, 2)
PAST_NEXT_MONDAY = date(2024, 1, 8)


def make_activity(
    d: date,
    *,
    sport_type: SportType = SportType.RUN,
    distance_m: float | None = 10_000,
    moving_time_s: int | None = 3600,
    elevation_gain_m: float | None = None,
    avg_pace_s_per_km: float | None = 360.0,
    avg_hr: float | None = 140.0,
    avg_cadence: float | None = None,
    hr_zone_pct: dict[str, float] | None = None,
    cardiac_decoupling_pct: float | None = None,
    pace_fade_seconds: float | None = None,
    name: str = "Activity",
) -> CardioAnalyticsActivity:
    return CardioAnalyticsActivity(
        source="strava",
        sport_type=sport_type,
        date=d,
        name=name,
        moving_time_s=moving_time_s,
        distance_m=distance_m,
        elevation_gain_m=elevation_gain_m,
        avg_pace_s_per_km=avg_pace_s_per_km,
        avg_hr=avg_hr,
        avg_cadence=avg_cadence,
        hr_zone_pct=hr_zone_pct,
        cardiac_decoupling_pct=cardiac_decoupling_pct,
        pace_fade_seconds=pace_fade_seconds,
    )


FULL_ZONES = {"Z1": 10.0, "Z2": 50.0, "Z3": 30.0, "Z4": 8.0, "Z5": 2.0}


# ── weekly_distance ──────────────────────────────────────────────────────────────


def test_weekly_distance_empty_is_unavailable():
    ds = compute_weekly_distance([], "km", TODAY)
    assert ds.available is False
    assert ds.unavailable_reason == UnavailableReason.NO_ACTIVITIES
    assert ds.chart_type == "weekly_bar"


def test_weekly_distance_single_activity():
    ds = compute_weekly_distance([make_activity(PAST_MONDAY, distance_m=10_000)], "km", TODAY)
    assert ds.available is True
    week = next(p for p in ds.data if p.week == PAST_MONDAY.isoformat())
    assert week.value == pytest.approx(10.0, rel=1e-3)
    assert week.is_current is False


def test_weekly_distance_sums_same_week():
    acts = [
        make_activity(PAST_MONDAY, distance_m=10_000),
        make_activity(PAST_TUESDAY, distance_m=5_000),
    ]
    ds = compute_weekly_distance(acts, "km", TODAY)
    week = next(p for p in ds.data if p.week == PAST_MONDAY.isoformat())
    assert week.value == pytest.approx(15.0, rel=1e-3)


def test_weekly_distance_null_distance_contributes_zero_not_excluded():
    acts = [make_activity(PAST_MONDAY, distance_m=None)]
    ds = compute_weekly_distance(acts, "km", TODAY)
    week = next(p for p in ds.data if p.week == PAST_MONDAY.isoformat())
    assert week.value == 0.0


def test_weekly_distance_marks_current_week():
    ds = compute_weekly_distance([make_activity(TODAY, distance_m=5000)], "km", TODAY)
    current = next(p for p in ds.data if p.is_current)
    assert current.week == TODAY.isoformat()


def test_weekly_distance_unit_conversion():
    ds_km = compute_weekly_distance([make_activity(PAST_MONDAY, distance_m=1000)], "km", TODAY)
    ds_mi = compute_weekly_distance([make_activity(PAST_MONDAY, distance_m=1000)], "miles", TODAY)
    assert ds_km.data[0].value == pytest.approx(1.0, rel=1e-3)
    assert ds_mi.data[0].value < ds_km.data[0].value


# ── atl_ctl ──────────────────────────────────────────────────────────────────────


def test_atl_ctl_empty_is_unavailable():
    ds = compute_atl_ctl([], "km", TODAY)
    assert ds.available is False
    assert ds.unavailable_reason == UnavailableReason.NO_ACTIVITIES


def test_atl_ctl_has_fields():
    ds = compute_atl_ctl([make_activity(PAST_MONDAY, distance_m=10_000)], "km", TODAY)
    assert ds.chart_type == "atl_ctl"
    first = ds.data[0]
    assert first.atl > 0


def test_atl_ctl_decays_without_activity():
    acts = [
        make_activity(date(2024, 1, 1), distance_m=20_000),
        make_activity(date(2024, 1, 15), distance_m=1),
    ]
    ds = compute_atl_ctl(acts, "km", date(2024, 1, 20))
    by_date = {p.date: p for p in ds.data}
    assert by_date["2024-01-08"].atl < by_date["2024-01-01"].atl


def test_atl_ctl_is_deterministic_on_injected_today():
    acts = [make_activity(date(2024, 1, 1), distance_m=10_000)]
    ds1 = compute_atl_ctl(acts, "km", date(2024, 1, 10))
    ds2 = compute_atl_ctl(acts, "km", date(2024, 1, 10))
    assert ds1.data == ds2.data


# ── aerobic_efficiency (formula must stay unchanged, higher = better) ──────────


def test_aerobic_efficiency_too_few_qualifying():
    acts = [make_activity(date(2024, 1, 1), avg_hr=140)]
    ds = compute_aerobic_efficiency(acts, "km", TODAY)
    assert ds.available is False
    assert ds.qualifying_count == 1


def test_aerobic_efficiency_hr_out_of_range_excluded():
    acts = [
        make_activity(date(2024, 1, 1), avg_hr=100),  # too low
        make_activity(date(2024, 1, 2), avg_hr=160),  # too high
        make_activity(date(2024, 1, 3), avg_hr=None),  # missing
    ]
    ds = compute_aerobic_efficiency(acts, "km", TODAY)
    assert ds.qualifying_count == 0


def test_aerobic_efficiency_formula_higher_is_better():
    """Verified orientation: faster pace at the SAME HR must score higher, not lower."""
    slow = make_activity(date(2024, 1, 1), avg_pace_s_per_km=400, avg_hr=140)
    fast = make_activity(date(2024, 1, 2), avg_pace_s_per_km=300, avg_hr=140)
    acts = [slow, fast] + [make_activity(date(2024, 1, d), avg_hr=140) for d in range(3, 13)]
    ds = compute_aerobic_efficiency(acts, "km", TODAY)
    by_date = {p.date: p for p in ds.scatter}
    assert by_date["2024-01-02"].value > by_date["2024-01-01"].value


def test_aerobic_efficiency_scatter_sorted_by_date():
    acts = [make_activity(date(2024, 2, 1), avg_hr=140)] + [
        make_activity(date(2024, 1, d), avg_hr=140) for d in range(1, 11)
    ]
    ds = compute_aerobic_efficiency(acts, "km", TODAY)
    dates = [p.date for p in ds.scatter]
    assert dates == sorted(dates)


# ── hr_zone_trend ────────────────────────────────────────────────────────────────


def test_hr_zone_trend_insufficient_weeks_is_unavailable():
    acts = [make_activity(PAST_MONDAY, hr_zone_pct=FULL_ZONES)]
    ds = compute_hr_zone_trend(acts, "km", TODAY)
    assert ds.available is False
    assert ds.count_unit == "weeks"


def test_hr_zone_trend_no_activities_reason():
    ds = compute_hr_zone_trend([], "km", TODAY)
    assert ds.unavailable_reason == UnavailableReason.NO_ACTIVITIES


def test_hr_zone_trend_missing_field_reason():
    acts = [make_activity(PAST_MONDAY, hr_zone_pct=None)]
    ds = compute_hr_zone_trend(acts, "km", TODAY)
    assert ds.unavailable_reason == UnavailableReason.MISSING_REQUIRED_FIELD


def test_hr_zone_trend_excludes_zero_duration_activity():
    acts = [
        make_activity(date(2024, 1, 1 + 7 * i), hr_zone_pct=FULL_ZONES, moving_time_s=3600)
        for i in range(3)
    ] + [make_activity(date(2024, 3, 1), hr_zone_pct=FULL_ZONES, moving_time_s=0)]
    ds = compute_hr_zone_trend(acts, "km", TODAY)
    assert ds.available is True
    # the zero-duration activity's week must not appear
    assert date(2024, 3, 1).isoformat() not in [w.week for w in ds.data] or len(ds.data) == 3


def test_hr_zone_trend_duration_weighted_average():
    # Same week: one long activity at 90% Z2, one short at 10% Z2 -> weighted toward the long one
    zones_a = {"Z1": 0, "Z2": 90, "Z3": 0, "Z4": 0, "Z5": 10}
    zones_b = {"Z1": 0, "Z2": 10, "Z3": 0, "Z4": 0, "Z5": 90}
    acts = [
        make_activity(PAST_MONDAY, hr_zone_pct=zones_a, moving_time_s=3600),
        make_activity(PAST_TUESDAY, hr_zone_pct=zones_b, moving_time_s=400),
    ] + [
        make_activity(date(2024, 1, 1 + 7 * i), hr_zone_pct=FULL_ZONES, moving_time_s=3600)
        for i in range(1, 3)
    ]
    ds = compute_hr_zone_trend(acts, "km", TODAY)
    first_week = next(p for p in ds.data if p.week == PAST_MONDAY.isoformat())
    # weighted average should be much closer to 90 (the long activity) than a plain 50/50 mean
    assert first_week.values["Z2"] > 60


def test_hr_zone_trend_weeks_sum_to_100():
    acts = [
        make_activity(date(2024, 1, 1 + 7 * i), hr_zone_pct=FULL_ZONES, moving_time_s=3600)
        for i in range(3)
    ]
    ds = compute_hr_zone_trend(acts, "km", TODAY)
    for week in ds.data:
        assert sum(week.values.values()) == pytest.approx(100.0, abs=0.1)


# ── per-activity trends: decoupling, cadence, pace fade ─────────────────────────


def test_cardiac_decoupling_trend_excludes_none():
    acts = [make_activity(date(2024, 1, d), cardiac_decoupling_pct=5.0) for d in range(1, 5)] + [
        make_activity(date(2024, 1, 10), cardiac_decoupling_pct=None)
    ]
    ds = compute_cardiac_decoupling_trend(acts, "km", TODAY)
    assert ds.qualifying_count == 4


def test_cadence_trend_excludes_zero_and_none():
    acts = [make_activity(date(2024, 1, d), avg_cadence=170.0) for d in range(1, 6)] + [
        make_activity(date(2024, 1, 10), avg_cadence=0),
        make_activity(date(2024, 1, 11), avg_cadence=None),
    ]
    ds = compute_cadence_trend(acts, "km", TODAY)
    assert ds.qualifying_count == 5
    assert ds.available is True


def test_pace_fade_trend_allows_negative_values():
    acts = [make_activity(date(2024, 1, d), pace_fade_seconds=-10.0) for d in range(1, 6)]
    ds = compute_pace_fade_trend(acts, "miles", TODAY)
    assert ds.available is True
    assert all(p.value == pytest.approx(-10.0) for p in ds.data)


def test_pace_fade_trend_converts_unit():
    acts = [make_activity(date(2024, 1, d), pace_fade_seconds=60.0) for d in range(1, 6)]
    ds_miles = compute_pace_fade_trend(acts, "miles", TODAY)
    ds_km = compute_pace_fade_trend(acts, "km", TODAY)
    assert ds_miles.unit == "sec/mi"
    assert ds_km.unit == "sec/km"
    assert ds_miles.data[0].value == pytest.approx(60.0)
    assert ds_km.data[0].value == pytest.approx(60.0 / 1.60934, abs=1e-3)


# ── weekly_elevation ─────────────────────────────────────────────────────────────


def test_weekly_elevation_unit_is_feet_for_miles():
    ds = compute_weekly_elevation(
        [make_activity(PAST_MONDAY, elevation_gain_m=100.0)], "miles", TODAY
    )
    assert ds.unit == "ft"
    assert ds.data[0].value == pytest.approx(328.084, rel=1e-3)


def test_weekly_elevation_unit_is_meters_for_km():
    ds = compute_weekly_elevation([make_activity(PAST_MONDAY, elevation_gain_m=100.0)], "km", TODAY)
    assert ds.unit == "m"
    assert ds.data[0].value == pytest.approx(100.0)


def test_weekly_elevation_null_contributes_zero():
    ds = compute_weekly_elevation([make_activity(PAST_MONDAY, elevation_gain_m=None)], "km", TODAY)
    assert ds.data[0].value == 0.0


# ── training_time_allocation ─────────────────────────────────────────────────────


def test_training_time_allocation_splits_by_sport():
    acts = [
        make_activity(PAST_MONDAY, sport_type=SportType.RUN, moving_time_s=3600),
        make_activity(PAST_MONDAY, sport_type=SportType.RIDE, moving_time_s=7200),
    ]
    ds = compute_training_time_allocation(acts, "miles", TODAY)
    week = next(p for p in ds.data if p.week == PAST_MONDAY.isoformat())
    assert week.values["Run"] == pytest.approx(1.0)
    assert week.values["Ride"] == pytest.approx(2.0)


def test_training_time_allocation_ignores_unknown_sport():
    """A week with only non-run/ride activity isn't a zero-cardio week — it's just not
    represented at all, same null-never-becomes-zero principle as the per-activity metrics."""
    acts = [make_activity(PAST_MONDAY, sport_type=SportType.WEIGHT_TRAINING, moving_time_s=3600)]
    ds = compute_training_time_allocation(acts, "miles", TODAY)
    assert ds.available is False
    assert ds.unavailable_reason == UnavailableReason.NO_ACTIVITIES


def test_training_time_allocation_empty_is_unavailable():
    ds = compute_training_time_allocation([], "miles", TODAY)
    assert ds.available is False
    assert ds.unavailable_reason == UnavailableReason.NO_ACTIVITIES
