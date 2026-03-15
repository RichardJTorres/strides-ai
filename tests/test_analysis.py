"""Unit tests for strides_ai.analysis — metric computation, NL summary, DB helpers."""

from unittest.mock import MagicMock, patch

import pytest

from strides_ai.analysis import (
    RateLimitError,
    _cadence_stats,
    _cardiac_decoupling,
    _effort_efficiency_raw,
    _elevation_metrics,
    _hr_zones,
    _pace_fade_seconds,
    _suffer_mismatch,
    build_analysis_summary,
    compute_metrics,
    condense_streams_for_deep_dive,
    fetch_activity_streams,
)
from strides_ai import db


# ── _cardiac_decoupling ───────────────────────────────────────────────────────


def test_cardiac_decoupling_basic():
    # First half HR/velocity = 150/3 = 50, second half = 165/3 = 55
    # decoupling = (55 - 50) / 50 * 100 = 10%
    hr = [150] * 50 + [165] * 50
    vel = [3.0] * 100
    result = _cardiac_decoupling(hr, vel)
    assert result == pytest.approx(10.0, abs=1.0)


def test_cardiac_decoupling_no_drift():
    hr = [150] * 100
    vel = [3.0] * 100
    result = _cardiac_decoupling(hr, vel)
    assert result == pytest.approx(0.0, abs=0.1)


def test_cardiac_decoupling_filters_low_velocity():
    # Stops are filtered out; 50 moving samples all have same HR/velocity ratio → 0.0
    hr = [150] * 50 + [165] * 50
    vel = [0.0] * 50 + [3.0] * 50  # first 50 stopped, second 50 moving
    result = _cardiac_decoupling(hr, vel)
    # 50 moving samples with uniform ratio in both halves → 0% decoupling
    assert result == pytest.approx(0.0, abs=0.1)


def test_cardiac_decoupling_mismatched_lengths_returns_none():
    assert _cardiac_decoupling([150, 160], [3.0]) is None


def test_cardiac_decoupling_empty_returns_none():
    assert _cardiac_decoupling([], []) is None


def test_cardiac_decoupling_too_few_samples_returns_none():
    # Need >= 10 moving samples total
    hr = [150] * 5
    vel = [3.0] * 5
    assert _cardiac_decoupling(hr, vel) is None


# ── _hr_zones ─────────────────────────────────────────────────────────────────


def test_hr_zones_all_z1(max_hr=190):
    # 100 bpm = 52.6% of 190 → all Z1
    hr = [100] * 100
    zones = _hr_zones(hr, max_hr=190)
    assert zones is not None
    assert zones["hr_zone_1_pct"] == pytest.approx(100.0)
    for z in range(2, 6):
        assert zones[f"hr_zone_{z}_pct"] == pytest.approx(0.0)


def test_hr_zones_all_z5():
    # 185 bpm = 97.4% of 190 → all Z5
    hr = [185] * 100
    zones = _hr_zones(hr, max_hr=190)
    assert zones is not None
    assert zones["hr_zone_5_pct"] == pytest.approx(100.0)


def test_hr_zones_sums_to_100():
    hr = [100, 115, 135, 155, 180] * 20  # mix of all zones
    zones = _hr_zones(hr, max_hr=190)
    assert zones is not None
    total = sum(zones.values())
    assert total == pytest.approx(100.0, abs=0.1)


def test_hr_zones_filters_zeros():
    # Mix of valid HR and zeros — zeros should be ignored
    hr = [0] * 50 + [150] * 50
    zones = _hr_zones(hr, max_hr=190)
    assert zones is not None
    # 150/190 = 79% → Z3
    assert zones["hr_zone_3_pct"] == pytest.approx(100.0)


def test_hr_zones_all_zeros_returns_none():
    assert _hr_zones([0, 0, 0], max_hr=190) is None


def test_hr_zones_empty_returns_none():
    assert _hr_zones([], max_hr=190) is None


def test_hr_zones_zone_boundaries():
    max_hr = 190
    # Exactly at Z2/Z3 boundary: 70% of 190 = 133
    zones_below = _hr_zones([132], max_hr=max_hr)
    zones_above = _hr_zones([133], max_hr=max_hr)
    assert zones_below["hr_zone_2_pct"] == pytest.approx(100.0)
    assert zones_above["hr_zone_3_pct"] == pytest.approx(100.0)


# ── _pace_fade_seconds ────────────────────────────────────────────────────────


def test_pace_fade_slowing():
    # 3 m/s in first third, 2 m/s in last third
    # pace at 3 m/s = 1609.34/3 ≈ 536.4 s/mile
    # pace at 2 m/s = 1609.34/2 ≈ 804.7 s/mile
    # fade ≈ 268 s/mile (positive = slowing)
    velocity = [3.0] * 30 + [2.5] * 30 + [2.0] * 30
    result = _pace_fade_seconds(velocity)
    assert result is not None
    assert result > 200  # positive = slowing


def test_pace_fade_negative_split():
    velocity = [2.0] * 30 + [2.5] * 30 + [3.0] * 30
    result = _pace_fade_seconds(velocity)
    assert result is not None
    assert result < -100  # negative = faster in final third


def test_pace_fade_steady_pace():
    velocity = [3.0] * 90
    result = _pace_fade_seconds(velocity)
    assert result == pytest.approx(0.0, abs=1.0)


def test_pace_fade_filters_near_zero():
    # Stops should be excluded
    velocity = [0.0] * 10 + [3.0] * 30 + [2.5] * 30 + [2.0] * 30
    result = _pace_fade_seconds(velocity)
    assert result is not None
    assert result > 0


def test_pace_fade_too_few_samples_returns_none():
    assert _pace_fade_seconds([3.0] * 5) is None


# ── _cadence_stats ────────────────────────────────────────────────────────────


def test_cadence_stats_run_doubles_values():
    cadence = [90.0] * 10  # raw half-cadence from Strava
    mean, std = _cadence_stats(cadence, is_run=True)
    assert mean == pytest.approx(180.0)
    assert std == pytest.approx(0.0)


def test_cadence_stats_cycle_no_doubling():
    cadence = [85.0] * 10
    mean, std = _cadence_stats(cadence, is_run=False)
    assert mean == pytest.approx(85.0)


def test_cadence_stats_std_dev():
    cadence = [80.0, 90.0, 100.0]
    mean, std = _cadence_stats(cadence, is_run=False)
    assert mean == pytest.approx(90.0)
    assert std is not None
    assert std > 0


def test_cadence_stats_single_value_std_is_none():
    mean, std = _cadence_stats([90.0], is_run=False)
    assert mean == pytest.approx(90.0)
    assert std is None


def test_cadence_stats_filters_zeros():
    cadence = [0, 0, 90.0, 90.0]
    mean, std = _cadence_stats(cadence, is_run=False)
    assert mean == pytest.approx(90.0)


def test_cadence_stats_all_zeros_returns_none():
    mean, std = _cadence_stats([0, 0, 0], is_run=False)
    assert mean is None
    assert std is None


# ── _effort_efficiency_raw ────────────────────────────────────────────────────


def test_effort_efficiency_raw_basic():
    # pace 360 s/km, hr 150 → 360/150 = 2.4
    result = _effort_efficiency_raw(360.0, 150.0)
    assert result == pytest.approx(2.4)


def test_effort_efficiency_raw_none_pace():
    assert _effort_efficiency_raw(None, 150.0) is None


def test_effort_efficiency_raw_none_hr():
    assert _effort_efficiency_raw(360.0, None) is None


def test_effort_efficiency_raw_zero_hr():
    assert _effort_efficiency_raw(360.0, 0.0) is None


def test_effort_efficiency_raw_negative_hr():
    assert _effort_efficiency_raw(360.0, -10.0) is None


# ── _elevation_metrics ────────────────────────────────────────────────────────


def test_elevation_metrics_flat():
    altitude = [100.0] * 100
    per_mile, flag = _elevation_metrics(altitude, distance_m=10000)
    assert per_mile == pytest.approx(0.0)
    assert flag == 0


def test_elevation_metrics_hilly():
    # 200m gain over 10km ≈ 6.2 miles → ~200*3.28/6.2 ≈ 105 ft/mile
    altitude = [float(i) for i in range(100)] + [100.0] * 100  # 99m gain
    altitude_hilly = [0.0, 200.0, 200.0, 0.0, 200.0, 200.0]  # 400m gain
    per_mile, flag = _elevation_metrics(altitude_hilly, distance_m=3218)  # 2 miles
    assert per_mile is not None
    assert flag in (0, 1)


def test_elevation_metrics_high_elevation_flag():
    # 200m (656 ft) gain over 1 mile (1609m) = 656 ft/mile → flag
    altitude = [0.0, 200.0]
    per_mile, flag = _elevation_metrics(altitude, distance_m=1609.34)
    assert per_mile is not None
    assert per_mile > 100
    assert flag == 1


def test_elevation_metrics_low_elevation_no_flag():
    # 30m (98 ft) gain over 1 mile → no flag
    altitude = [0.0, 30.0]
    per_mile, flag = _elevation_metrics(altitude, distance_m=1609.34)
    assert flag == 0


def test_elevation_metrics_no_altitude_returns_none():
    assert _elevation_metrics([], distance_m=10000) == (None, None)


def test_elevation_metrics_zero_distance_returns_none():
    assert _elevation_metrics([100.0, 110.0], distance_m=0) == (None, None)


# ── _suffer_mismatch ──────────────────────────────────────────────────────────


def test_suffer_mismatch_high_suffer_low_intensity():
    # suffer=60, z4+z5=10% → mismatch
    assert _suffer_mismatch(60, 7.0, 3.0) == 1


def test_suffer_mismatch_low_suffer_high_intensity():
    # suffer=10, z4+z5=35% → mismatch
    assert _suffer_mismatch(10, 20.0, 15.0) == 1


def test_suffer_mismatch_consistent_no_flag():
    # suffer=70, z4+z5=40% → consistent
    assert _suffer_mismatch(70, 25.0, 15.0) == 0


def test_suffer_mismatch_none_suffer_returns_none():
    assert _suffer_mismatch(None, 10.0, 5.0) is None


def test_suffer_mismatch_none_zones_returns_none():
    assert _suffer_mismatch(60, None, None) is None


# ── build_analysis_summary ────────────────────────────────────────────────────


def test_summary_strong_aerobic():
    metrics = {
        "cardiac_decoupling_pct": 3.0,
        "hr_zone_1_pct": 40.0,
        "hr_zone_2_pct": 45.0,
        "hr_zone_3_pct": 10.0,
        "hr_zone_4_pct": 3.0,
        "hr_zone_5_pct": 2.0,
        "pace_fade_seconds": 5.0,
        "high_elevation_flag": 0,
        "suffer_score_mismatch_flag": 0,
    }
    summary = build_analysis_summary(metrics)
    assert "Strong aerobic" in summary
    assert "3.0%" in summary


def test_summary_high_cardiac_stress():
    metrics = {
        "cardiac_decoupling_pct": 14.0,
        "hr_zone_1_pct": 5.0,
        "hr_zone_2_pct": 10.0,
        "hr_zone_3_pct": 15.0,
        "hr_zone_4_pct": 35.0,
        "hr_zone_5_pct": 35.0,
        "pace_fade_seconds": 0.0,
        "high_elevation_flag": 0,
        "suffer_score_mismatch_flag": 0,
    }
    summary = build_analysis_summary(metrics)
    assert "High cardiac stress" in summary


def test_summary_includes_pace_fade_when_significant():
    metrics = {
        "cardiac_decoupling_pct": 5.0,
        "hr_zone_1_pct": 50.0,
        "hr_zone_2_pct": 30.0,
        "hr_zone_3_pct": 10.0,
        "hr_zone_4_pct": 5.0,
        "hr_zone_5_pct": 5.0,
        "pace_fade_seconds": 30.0,
        "high_elevation_flag": 0,
        "suffer_score_mismatch_flag": 0,
    }
    summary = build_analysis_summary(metrics)
    assert "30" in summary
    assert "pace fade" in summary.lower() or "slowed" in summary.lower()


def test_summary_ignores_small_pace_fade():
    metrics = {
        "cardiac_decoupling_pct": 4.0,
        "pace_fade_seconds": 5.0,
        "hr_zone_1_pct": 60.0,
        "hr_zone_2_pct": 30.0,
        "hr_zone_3_pct": 5.0,
        "hr_zone_4_pct": 3.0,
        "hr_zone_5_pct": 2.0,
        "high_elevation_flag": 0,
        "suffer_score_mismatch_flag": 0,
    }
    summary = build_analysis_summary(metrics)
    # pace fade of 5 is insignificant — should not appear
    assert "fade" not in summary.lower()


def test_summary_hilly_course():
    metrics = {
        "cardiac_decoupling_pct": 4.0,
        "hr_zone_1_pct": 40.0,
        "hr_zone_2_pct": 40.0,
        "hr_zone_3_pct": 10.0,
        "hr_zone_4_pct": 5.0,
        "hr_zone_5_pct": 5.0,
        "pace_fade_seconds": 0.0,
        "high_elevation_flag": 1,
        "elevation_per_mile": 150.0,
        "suffer_score_mismatch_flag": 0,
    }
    summary = build_analysis_summary(metrics)
    assert "150" in summary or "Hilly" in summary


def test_summary_mismatch_warning():
    metrics = {
        "cardiac_decoupling_pct": 6.0,
        "hr_zone_1_pct": 50.0,
        "hr_zone_2_pct": 30.0,
        "hr_zone_3_pct": 10.0,
        "hr_zone_4_pct": 5.0,
        "hr_zone_5_pct": 5.0,
        "pace_fade_seconds": 0.0,
        "high_elevation_flag": 0,
        "suffer_score_mismatch_flag": 1,
    }
    summary = build_analysis_summary(metrics)
    assert "unreliable" in summary.lower() or "Note" in summary


def test_summary_no_cardiac_data():
    metrics = {
        "cardiac_decoupling_pct": None,
        "hr_zone_1_pct": None,
        "hr_zone_2_pct": None,
        "hr_zone_3_pct": None,
        "hr_zone_4_pct": None,
        "hr_zone_5_pct": None,
        "pace_fade_seconds": None,
        "high_elevation_flag": 0,
        "suffer_score_mismatch_flag": None,
    }
    summary = build_analysis_summary(metrics)
    assert len(summary) > 0  # should not crash


# ── compute_metrics ───────────────────────────────────────────────────────────


def test_compute_metrics_full_streams():
    streams = {
        "time": list(range(0, 600, 1)),
        "heartrate": [150] * 300 + [165] * 300,
        "velocity_smooth": [3.0] * 600,
        "cadence": [90.0] * 600,
        "altitude": [100.0] * 600,
    }
    activity = {
        "id": 1,
        "sport_type": "Run",
        "distance_m": 1800.0,
        "avg_pace_s_per_km": 360.0,
        "avg_hr": 157.0,
        "suffer_score": 40,
    }
    metrics = compute_metrics(streams, activity, max_hr=190)
    assert "cardiac_decoupling_pct" in metrics
    assert "hr_zone_1_pct" in metrics
    assert "pace_fade_seconds" in metrics
    assert "avg_cadence" in metrics  # maps to existing DB column
    assert "cadence_std_dev" in metrics
    assert "effort_efficiency_raw" in metrics
    assert "elevation_per_mile" in metrics
    assert "high_elevation_flag" in metrics


def test_compute_metrics_missing_hr():
    streams = {
        "time": list(range(0, 300)),
        "velocity_smooth": [3.0] * 300,
    }
    activity = {
        "id": 1,
        "sport_type": "Run",
        "distance_m": 900.0,
        "avg_pace_s_per_km": 360.0,
        "avg_hr": None,
    }
    metrics = compute_metrics(streams, activity, max_hr=190)
    assert metrics["cardiac_decoupling_pct"] is None
    assert metrics["hr_zone_1_pct"] is None


def test_compute_metrics_avg_cadence_key_used_not_cadence_avg():
    """Ensure the returned key is 'avg_cadence' (existing DB column), not 'cadence_avg'."""
    streams = {"cadence": [90.0] * 100}
    activity = {
        "id": 1,
        "sport_type": "Run",
        "distance_m": 1000.0,
        "avg_pace_s_per_km": 360.0,
        "avg_hr": 150.0,
    }
    metrics = compute_metrics(streams, activity)
    assert "avg_cadence" in metrics
    assert "cadence_avg" not in metrics


def test_compute_metrics_empty_streams_returns_none_values():
    activity = {
        "id": 1,
        "sport_type": "Run",
        "distance_m": 0,
        "avg_pace_s_per_km": None,
        "avg_hr": None,
    }
    metrics = compute_metrics({}, activity)
    assert metrics["cardiac_decoupling_pct"] is None
    assert metrics["effort_efficiency_raw"] is None


# ── fetch_activity_streams ────────────────────────────────────────────────────


def test_fetch_streams_success():
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "heartrate": {"data": [150, 155, 160]},
        "velocity_smooth": {"data": [3.0, 3.1, 2.9]},
    }

    with patch("strides_ai.analysis.httpx.Client") as MockClient:
        MockClient.return_value.__enter__.return_value.get.return_value = mock_response
        result = fetch_activity_streams(12345, "fake_token")

    assert result["heartrate"] == [150, 155, 160]
    assert result["velocity_smooth"] == [3.0, 3.1, 2.9]


def test_fetch_streams_404_returns_empty():
    mock_response = MagicMock()
    mock_response.status_code = 404

    with patch("strides_ai.analysis.httpx.Client") as MockClient:
        MockClient.return_value.__enter__.return_value.get.return_value = mock_response
        result = fetch_activity_streams(12345, "fake_token")

    assert result == {}


def test_fetch_streams_429_raises_rate_limit_error():
    mock_response = MagicMock()
    mock_response.status_code = 429

    with patch("strides_ai.analysis.httpx.Client") as MockClient:
        MockClient.return_value.__enter__.return_value.get.return_value = mock_response
        with pytest.raises(RateLimitError):
            fetch_activity_streams(12345, "fake_token")


def test_fetch_streams_network_error_returns_empty():
    with patch("strides_ai.analysis.httpx.Client") as MockClient:
        MockClient.return_value.__enter__.return_value.get.side_effect = Exception("timeout")
        result = fetch_activity_streams(12345, "fake_token")

    assert result == {}


# ── renormalize_effort_efficiency ─────────────────────────────────────────────


def test_renormalize_effort_efficiency(tmp_db):
    """Most efficient activity (lowest raw ratio) should score 100."""
    # Insert 3 activities with different efficiency: lower raw = more efficient
    for i, (activity_id, raw) in enumerate([(1, 1.5), (2, 2.5), (3, 3.5)], 1):
        db.upsert_activity(
            {
                "id": activity_id,
                "name": f"Run {i}",
                "start_date_local": f"2025-0{i}-01T07:00:00Z",
                "distance": 10000,
                "moving_time": 3600,
                "elapsed_time": 3700,
                "sport_type": "Run",
            }
        )
        db.save_analysis(activity_id, {"effort_efficiency_raw": raw})

    db.renormalize_effort_efficiency()

    activities = db.get_all_activities()
    scores = {a["id"]: a["effort_efficiency_score"] for a in activities}

    # Activity 1 has lowest raw (most efficient) → should score 100
    assert scores[1] == pytest.approx(100.0)
    # Activity 3 has highest raw (least efficient) → should score 0
    assert scores[3] == pytest.approx(0.0)
    # Activity 2 is in the middle
    assert 0 < scores[2] < 100


def test_renormalize_single_activity_scores_50(tmp_db):
    db.upsert_activity(
        {
            "id": 1,
            "name": "Solo Run",
            "start_date_local": "2025-01-01T07:00:00Z",
            "distance": 10000,
            "moving_time": 3600,
            "elapsed_time": 3700,
            "sport_type": "Run",
        }
    )
    db.save_analysis(1, {"effort_efficiency_raw": 2.0})
    db.renormalize_effort_efficiency()

    row = db.get_all_activities()[0]
    assert row["effort_efficiency_score"] == pytest.approx(50.0)


# ── condense_streams_for_deep_dive ────────────────────────────────────────────


def test_condense_streams_produces_table():
    streams = {
        "time": list(range(0, 600, 10)),
        "heartrate": [150] * 60,
        "velocity_smooth": [3.0] * 60,
        "cadence": [90.0] * 60,
        "altitude": [100.0] * 60,
    }
    activity = {
        "id": 1,
        "name": "Test Run",
        "date": "2025-06-15",
        "distance_m": 1800,
        "sport_type": "Run",
    }
    output = condense_streams_for_deep_dive(streams, activity)
    assert "ELAPSED" in output
    assert "PACE" in output
    assert "HR" in output


def test_condense_streams_empty_returns_fallback():
    output = condense_streams_for_deep_dive({}, {"id": 1, "name": "Empty"})
    assert "No stream data" in output


def test_condense_streams_cycling_shows_speed():
    streams = {
        "time": list(range(0, 600, 10)),
        "velocity_smooth": [8.0] * 60,
    }
    activity = {
        "id": 1,
        "name": "Ride",
        "date": "2025-06-15",
        "distance_m": 4800,
        "sport_type": "Ride",
    }
    output = condense_streams_for_deep_dive(streams, activity)
    assert "SPEED" in output
    assert "PACE" not in output
