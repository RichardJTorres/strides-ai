"""Unit tests for strides_ai.charts_data — all pure functions."""

from datetime import date, timedelta

import pytest

from strides_ai.charts_data import (
    M_TO_KM,
    M_TO_MI,
    _dist,
    _pace,
    compute_aerobic_efficiency,
    compute_atl_ctl,
    compute_weekly_mileage,
    get_chart_data,
)

# ── Helpers ───────────────────────────────────────────────────────────────────


def make_activity(
    date_str: str,
    distance_m: float = 10_000,
    avg_pace_s_per_km: float = 360.0,
    avg_hr: float | None = 140.0,
    name: str = "Run",
):
    return {
        "date": date_str,
        "distance_m": distance_m,
        "avg_pace_s_per_km": avg_pace_s_per_km,
        "avg_hr": avg_hr,
        "name": name,
    }


# Use fixed past dates that will never be "current week"
PAST_MONDAY = "2024-01-01"  # Monday
PAST_TUESDAY = "2024-01-02"
PAST_NEXT_MONDAY = "2024-01-08"


# ── _dist ─────────────────────────────────────────────────────────────────────


def test_dist_miles():
    assert _dist(1000, "miles") == pytest.approx(1000 * M_TO_MI)


def test_dist_km():
    assert _dist(1000, "km") == pytest.approx(1.0)


def test_dist_zero():
    assert _dist(0, "miles") == 0.0


def test_dist_none_treated_as_zero():
    assert _dist(None, "km") == 0.0


# ── _pace ─────────────────────────────────────────────────────────────────────


def test_pace_km_is_identity():
    assert _pace(300.0, "km") == pytest.approx(300.0)


def test_pace_miles_converts():
    # 1 km pace × 1.60934 = 1 mile pace
    assert _pace(300.0, "miles") == pytest.approx(300.0 * 1.60934)


# ── compute_weekly_mileage ────────────────────────────────────────────────────


def test_weekly_mileage_empty():
    assert compute_weekly_mileage([], "km") == []


def test_weekly_mileage_single_run():
    acts = [make_activity(PAST_MONDAY, distance_m=10_000)]
    result = compute_weekly_mileage(acts, "km")
    # First entry is the week containing PAST_MONDAY
    week_entry = result[0]
    assert week_entry["week"] == PAST_MONDAY
    assert week_entry["distance"] == pytest.approx(10.0, rel=1e-3)


def test_weekly_mileage_two_runs_same_week():
    acts = [
        make_activity(PAST_MONDAY, distance_m=10_000),
        make_activity(PAST_TUESDAY, distance_m=5_000),
    ]
    result = compute_weekly_mileage(acts, "km")
    first_week = result[0]
    assert first_week["distance"] == pytest.approx(15.0, rel=1e-3)


def test_weekly_mileage_two_separate_weeks():
    acts = [
        make_activity(PAST_MONDAY, distance_m=10_000),
        make_activity(PAST_NEXT_MONDAY, distance_m=8_000),
    ]
    result = compute_weekly_mileage(acts, "km")
    # At minimum two non-zero weeks
    non_zero = [r for r in result if r["distance"] > 0]
    assert len(non_zero) == 2


def test_weekly_mileage_rolling_avg_single_week():
    acts = [make_activity(PAST_MONDAY, distance_m=10_000)]
    result = compute_weekly_mileage(acts, "km")
    # Rolling avg of 1 week = that week's distance
    assert result[0]["rolling_avg"] == pytest.approx(result[0]["distance"])


def test_weekly_mileage_has_is_current_field():
    acts = [make_activity(PAST_MONDAY)]
    result = compute_weekly_mileage(acts, "km")
    assert all("is_current" in r for r in result)


def test_weekly_mileage_past_week_not_current():
    acts = [make_activity(PAST_MONDAY)]
    result = compute_weekly_mileage(acts, "km")
    assert result[0]["is_current"] is False


def test_weekly_mileage_unit_miles():
    acts = [make_activity(PAST_MONDAY, distance_m=1_609.34)]  # ~1 mile
    result = compute_weekly_mileage(acts, "miles")
    assert result[0]["distance"] == pytest.approx(1.0, rel=1e-3)


# ── compute_atl_ctl ───────────────────────────────────────────────────────────


def test_atl_ctl_empty():
    assert compute_atl_ctl([], "km") == []


def test_atl_ctl_returns_list_of_dicts():
    acts = [make_activity(PAST_MONDAY)]
    result = compute_atl_ctl(acts, "km")
    assert isinstance(result, list)
    assert len(result) >= 1
    assert {"date", "atl", "ctl", "ratio"} == set(result[0].keys())


def test_atl_ctl_first_day_has_nonzero_atl():
    acts = [make_activity(PAST_MONDAY, distance_m=10_000)]
    result = compute_atl_ctl(acts, "km")
    # First day after a 10km run should have positive ATL
    first = result[0]
    assert first["atl"] > 0


def test_atl_ctl_atl_decays_without_runs():
    # Two weeks apart — ATL should be higher on the run day than later
    d1 = "2024-01-01"
    d2 = "2024-01-15"
    acts = [make_activity(d1, distance_m=20_000), make_activity(d2, distance_m=1)]
    result = compute_atl_ctl(acts, "km")
    by_date = {r["date"]: r for r in result}
    # ATL on day of first run
    atl_day1 = by_date[d1]["atl"]
    # ATL a week later (no run in between) should be lower
    atl_week_later = by_date["2024-01-08"]["atl"]
    assert atl_week_later < atl_day1


def test_atl_ctl_ratio_none_when_ctl_negligible():
    # A single run early in history: CTL may still be > 1e-3 but ratio check covers edge
    acts = [make_activity(PAST_MONDAY, distance_m=100)]
    result = compute_atl_ctl(acts, "km")
    first = result[0]
    if first["ctl"] <= 1e-3:
        assert first["ratio"] is None
    else:
        assert first["ratio"] is not None


# ── compute_aerobic_efficiency ────────────────────────────────────────────────


def test_aerobic_efficiency_empty():
    result = compute_aerobic_efficiency([], "km")
    assert result["has_enough_data"] is False
    assert result["qualifying_count"] == 0


def test_aerobic_efficiency_too_few_runs():
    acts = [make_activity("2024-01-01", avg_hr=140)]
    result = compute_aerobic_efficiency(acts, "km")
    assert result["has_enough_data"] is False
    assert result["qualifying_count"] == 1


def test_aerobic_efficiency_hr_out_of_range_excluded():
    # HR below 120 and above 155 should be excluded
    acts = [
        make_activity("2024-01-01", avg_hr=100),  # too low
        make_activity("2024-01-02", avg_hr=160),  # too high
        make_activity("2024-01-03", avg_hr=None),  # missing
    ]
    result = compute_aerobic_efficiency(acts, "km")
    assert result["qualifying_count"] == 0


def test_aerobic_efficiency_has_enough_data():
    # Build 12 qualifying runs with HR in range
    acts = [
        make_activity(f"2024-0{m}-{d:02d}", avg_hr=140, avg_pace_s_per_km=360)
        for m in range(1, 3)
        for d in range(1, 7)
    ]
    result = compute_aerobic_efficiency(acts, "km")
    assert result["has_enough_data"] is True
    assert result["qualifying_count"] == 12
    assert len(result["scatter"]) == 12
    assert len(result["rolling_avg"]) == 12


def test_aerobic_efficiency_efficiency_formula():
    # One qualifying run: 10km in 60min (360 s/km), HR 145
    acts = [make_activity("2024-01-01", avg_pace_s_per_km=360, avg_hr=145)]
    result = compute_aerobic_efficiency(acts, "km")
    pt = result["scatter"][0]
    # speed = 3600 / 360 = 10 unit/hr; eff = 10 / 145 * 100
    expected = (3600.0 / 360.0) / 145.0 * 100.0
    assert pt["efficiency"] == pytest.approx(expected, rel=1e-3)


def test_aerobic_efficiency_scatter_sorted_by_date():
    acts = [
        make_activity("2024-02-01", avg_hr=140),
        make_activity("2024-01-01", avg_hr=140),
    ]
    result = compute_aerobic_efficiency(acts, "km")
    dates = [p["date"] for p in result["scatter"]]
    assert dates == sorted(dates)


# ── get_chart_data ─────────────────────────────────────────────────────────────


def test_get_chart_data_structure():
    acts = [make_activity(PAST_MONDAY)]
    result = get_chart_data(acts, "km")
    assert set(result.keys()) == {"unit", "weekly_mileage", "atl_ctl", "aerobic_efficiency"}
    assert result["unit"] == "km"


def test_get_chart_data_empty():
    result = get_chart_data([], "miles")
    assert result["weekly_mileage"] == []
    assert result["atl_ctl"] == []
    assert result["aerobic_efficiency"]["qualifying_count"] == 0


def test_get_chart_data_accepts_row_like_objects():
    """get_chart_data converts rows via dict() — test it handles plain dicts."""
    acts = [make_activity(PAST_MONDAY, distance_m=5000)]
    result = get_chart_data(acts, "km")
    assert result["weekly_mileage"][0]["distance"] == pytest.approx(5.0, rel=1e-3)
