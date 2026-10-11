"""Unit tests for strides_ai.analytics.composition — explicit, ordered mode -> chart sets."""

from datetime import date

from strides_ai.analytics.composition import (
    CYCLING_CHARTS,
    HYBRID_CHARTS,
    RIDE_SPECIFIC,
    RUN_SPECIFIC,
    RUNNING_CHARTS,
    get_chart_datasets,
)

TODAY = date(2026, 6, 1)


def make_row(sport_type: str, d: str) -> dict:
    return {
        "source": "strava",
        "sport_type": sport_type,
        "date": d,
        "name": "Activity",
        "moving_time_s": 3600,
        "distance_m": 10_000,
        "elevation_gain_m": 100.0,
        "avg_pace_s_per_km": 300.0,
        "avg_hr": 140.0,
        "avg_cadence": 170.0,
    }


# ── ordering and scope per mode ─────────────────────────────────────────────────


def test_running_excludes_elevation_and_allocation():
    keys = [spec.key for spec in RUNNING_CHARTS]
    assert "weekly_elevation" not in keys
    assert "training_time_allocation" not in keys
    assert "cadence_trend" in keys


def test_cycling_excludes_cadence_and_pace_fade():
    keys = [spec.key for spec in CYCLING_CHARTS]
    assert "cadence_trend" not in keys
    assert "pace_fade_trend" not in keys
    assert "weekly_elevation" in keys


def test_hybrid_includes_sport_prefixed_variants_in_order():
    keys = [spec.key for spec in HYBRID_CHARTS]
    assert keys[0] == "weekly_distance"
    assert keys[1] == "atl_ctl"
    assert keys[-1] == "training_time_allocation"
    assert "run_aerobic_efficiency" in keys
    assert "ride_aerobic_efficiency" in keys
    assert "run_cadence_trend" in keys
    assert "ride_weekly_elevation" in keys
    # cycling-only/running-only metrics must not leak into the wrong sport's hybrid half
    assert "ride_cadence_trend" not in keys
    assert "run_weekly_elevation" not in keys


def test_hybrid_replace_does_not_mutate_base_lists():
    """dataclasses.replace() must not have mutated RUN_SPECIFIC/RIDE_SPECIFIC in place."""
    assert all(spec.sport_filter is None for spec in RUN_SPECIFIC)
    assert all(spec.sport_filter is None for spec in RIDE_SPECIFIC)
    assert all(not spec.key.startswith("run_") for spec in RUN_SPECIFIC)
    assert all(not spec.key.startswith("ride_") for spec in RIDE_SPECIFIC)


# ── get_chart_datasets: id / metric_key / sport correctness ────────────────────


def test_get_chart_datasets_running_ids_match_metric_keys():
    rows = [make_row("Run", "2026-05-01")]
    datasets = get_chart_datasets(rows, "running", "miles", today=TODAY)
    for ds in datasets:
        assert ds.id == ds.metric_key
        assert ds.sport == "run"


def test_get_chart_datasets_hybrid_ids_are_unique_and_prefixed():
    rows = [make_row("Run", "2026-05-01"), make_row("Ride", "2026-05-02")]
    datasets = get_chart_datasets(rows, "hybrid", "miles", today=TODAY)
    ids = [ds.id for ds in datasets]
    assert len(ids) == len(set(ids))  # all unique

    run_ae = next(d for d in datasets if d.id == "run_aerobic_efficiency")
    ride_ae = next(d for d in datasets if d.id == "ride_aerobic_efficiency")
    assert run_ae.metric_key == ride_ae.metric_key == "aerobic_efficiency"
    assert run_ae.sport == "run"
    assert ride_ae.sport == "ride"


def test_get_chart_datasets_hybrid_sport_filter_partitions_activities():
    rows = [make_row("Run", "2026-05-01"), make_row("Ride", "2026-05-02")]
    datasets = get_chart_datasets(rows, "hybrid", "miles", today=TODAY)
    allocation = next(d for d in datasets if d.id == "training_time_allocation")
    assert allocation.available is True  # combined chart sees both sports

    run_elevation_leak = [d for d in datasets if d.id == "run_weekly_elevation"]
    assert run_elevation_leak == []  # not part of the composition at all


def test_get_chart_datasets_unknown_mode_falls_back_to_running():
    rows = [make_row("Run", "2026-05-01")]
    datasets = get_chart_datasets(rows, "not-a-real-mode", "miles", today=TODAY)
    ids = [ds.id for ds in datasets]
    assert ids == [spec.key for spec in RUNNING_CHARTS]


def test_get_chart_datasets_defaults_today_when_not_provided():
    rows = [make_row("Run", "2026-05-01")]
    datasets = get_chart_datasets(rows, "running", "miles")  # no today= passed
    assert any(ds.available for ds in datasets)
