"""Unit tests for strides_ai.analytics.adapters — the DB-row validation boundary."""

import math
from datetime import date

from strides_ai.activity_types import SportType
from strides_ai.analytics.adapters import to_cardio_analytics
from strides_ai.analytics.cardio import compute_cadence_trend, compute_cardiac_decoupling_trend

TODAY = date(2026, 6, 1)


def make_row(**overrides) -> dict:
    row = {
        "source": "strava",
        "sport_type": "Run",
        "date": "2026-01-05",
        "name": "Morning Run",
        "moving_time_s": 1800,
        "distance_m": 5000.0,
        "elevation_gain_m": 50.0,
        "avg_pace_s_per_km": 300.0,
        "avg_hr": 140.0,
        "avg_cadence": 170.0,
        "hr_zone_1_pct": 10.0,
        "hr_zone_2_pct": 50.0,
        "hr_zone_3_pct": 30.0,
        "hr_zone_4_pct": 8.0,
        "hr_zone_5_pct": 2.0,
        "cardiac_decoupling_pct": 4.5,
        "pace_fade_seconds": 12.0,
    }
    row.update(overrides)
    return row


# ── basic conversion ─────────────────────────────────────────────────────────────


def test_converts_basic_fields():
    [a] = to_cardio_analytics([make_row()])
    assert a.source == "strava"
    assert a.sport_type == SportType.RUN
    assert a.name == "Morning Run"
    assert a.distance_m == 5000.0
    assert a.hr_zone_pct == {"Z1": 10.0, "Z2": 50.0, "Z3": 30.0, "Z4": 8.0, "Z5": 2.0}


def test_unknown_sport_type_falls_back_to_unknown():
    [a] = to_cardio_analytics([make_row(sport_type="SomeNewSport")])
    assert a.sport_type == SportType.UNKNOWN


def test_missing_source_defaults_to_unknown_string():
    [a] = to_cardio_analytics([make_row(source=None)])
    assert a.source == "unknown"


# ── validation boundary: dropped / normalized rows ──────────────────────────────


def test_row_with_unparseable_date_is_dropped():
    rows = [make_row(date="not-a-date"), make_row(date="2026-01-06")]
    result = to_cardio_analytics(rows)
    assert len(result) == 1
    assert result[0].date.isoformat() == "2026-01-06"


def test_row_with_missing_date_is_dropped():
    rows = [make_row(date=None)]
    assert to_cardio_analytics(rows) == []


def test_partial_hr_zones_become_none_not_partial():
    """If even one zone is missing, the whole hr_zone_pct dict is None — never partially filled."""
    [a] = to_cardio_analytics([make_row(hr_zone_5_pct=None)])
    assert a.hr_zone_pct is None


def test_non_finite_hr_zone_becomes_none():
    [a] = to_cardio_analytics([make_row(hr_zone_3_pct=math.nan)])
    assert a.hr_zone_pct is None


def test_non_finite_avg_hr_becomes_none():
    [a] = to_cardio_analytics([make_row(avg_hr=math.inf)])
    assert a.avg_hr is None


def test_non_finite_cardiac_decoupling_becomes_none():
    [a] = to_cardio_analytics([make_row(cardiac_decoupling_pct=math.nan)])
    assert a.cardiac_decoupling_pct is None


# ── source independence ──────────────────────────────────────────────────────────


def test_source_independence_identical_normalized_inputs_same_results():
    """Two activities differing only in `source` must produce identical cardio.py output."""
    strava_row = make_row(source="strava")
    other_row = make_row(source="some_other_provider")

    strava_activities = to_cardio_analytics([strava_row] * 6)
    other_activities = to_cardio_analytics([other_row] * 6)

    strava_decoupling = compute_cardiac_decoupling_trend(strava_activities, "miles", TODAY)
    other_decoupling = compute_cardiac_decoupling_trend(other_activities, "miles", TODAY)
    assert [p.value for p in strava_decoupling.data] == [p.value for p in other_decoupling.data]

    strava_cadence = compute_cadence_trend(strava_activities, "miles", TODAY)
    other_cadence = compute_cadence_trend(other_activities, "miles", TODAY)
    assert [p.value for p in strava_cadence.data] == [p.value for p in other_cadence.data]


def test_invalid_base_metrics_are_unavailable_and_serialize_safely():
    from strides_ai.analytics.composition import get_chart_datasets

    row = make_row(
        distance_m=math.nan,
        moving_time_s=math.inf,
        elevation_gain_m=-10,
        avg_pace_s_per_km=math.inf,
    )
    [activity] = to_cardio_analytics([row])
    assert activity.distance_m is None
    assert activity.moving_time_s is None
    assert activity.elevation_gain_m is None
    assert activity.avg_pace_s_per_km is None
    for dataset in get_chart_datasets([row] * 10, "running", "km", TODAY):
        assert "NaN" not in dataset.model_dump_json()
        assert "Infinity" not in dataset.model_dump_json()


def test_out_of_range_or_inconsistent_zone_percentages_are_unavailable():
    for zones in ({"hr_zone_1_pct": -1}, {"hr_zone_1_pct": 101}, {"hr_zone_1_pct": 0}):
        [activity] = to_cardio_analytics([make_row(**zones)])
        assert activity.hr_zone_pct is None
