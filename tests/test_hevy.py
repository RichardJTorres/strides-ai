"""Unit tests for HEVY sync transform and analysis metrics."""

import json

import pytest

from strides_ai.hevy_analysis import compute_hevy_metrics, estimate_1rm
from strides_ai.hevy_sync import _compute_volume, _transform_workout


# ── estimate_1rm ──────────────────────────────────────────────────────────────


def test_estimate_1rm_basic():
    # 100 kg × 5 reps: 100 * (1 + 5/30) = 116.7
    result = estimate_1rm(100.0, 5)
    assert result == pytest.approx(116.7, abs=0.1)


def test_estimate_1rm_single_rep():
    # 1 rep: 140 * (1 + 1/30) ≈ 144.7
    result = estimate_1rm(140.0, 1)
    assert result == pytest.approx(140.0 * (1 + 1 / 30), abs=0.1)


def test_estimate_1rm_zero_weight_returns_none():
    assert estimate_1rm(0.0, 5) is None


def test_estimate_1rm_zero_reps_returns_none():
    assert estimate_1rm(100.0, 0) is None


def test_estimate_1rm_high_reps_returns_none():
    # More than 12 reps is unreliable
    assert estimate_1rm(60.0, 15) is None


def test_estimate_1rm_exactly_12_reps():
    # 12 reps should still return a value
    result = estimate_1rm(80.0, 12)
    assert result is not None


# ── _compute_volume ───────────────────────────────────────────────────────────


def test_compute_volume_basic():
    exercises = [
        {
            "sets": [
                {"type": "normal", "weight_kg": 100.0, "reps": 5},
                {"type": "normal", "weight_kg": 100.0, "reps": 5},
                {"type": "normal", "weight_kg": 100.0, "reps": 5},
            ]
        }
    ]
    volume, sets = _compute_volume(exercises)
    assert volume == pytest.approx(1500.0)
    assert sets == 3


def test_compute_volume_skips_warmup():
    exercises = [
        {
            "sets": [
                {"type": "warmup", "weight_kg": 60.0, "reps": 10},
                {"type": "normal", "weight_kg": 100.0, "reps": 5},
            ]
        }
    ]
    volume, sets = _compute_volume(exercises)
    assert volume == pytest.approx(500.0)
    assert sets == 1


def test_compute_volume_handles_missing_weight():
    exercises = [
        {
            "sets": [
                {"type": "normal", "weight_kg": None, "reps": 10},  # bodyweight
            ]
        }
    ]
    volume, sets = _compute_volume(exercises)
    assert volume == pytest.approx(0.0)
    assert sets == 1


def test_compute_volume_multiple_exercises():
    exercises = [
        {"sets": [{"type": "normal", "weight_kg": 100.0, "reps": 5}]},
        {"sets": [{"type": "normal", "weight_kg": 80.0, "reps": 8}]},
    ]
    volume, sets = _compute_volume(exercises)
    assert volume == pytest.approx(100 * 5 + 80 * 8)
    assert sets == 2


# ── _transform_workout ────────────────────────────────────────────────────────


_SAMPLE_WORKOUT = {
    "id": "aabbccdd-1234-5678-abcd-ef0123456789",
    "title": "Push Day",
    "start_time": "2026-04-20T09:00:00Z",
    "end_time": "2026-04-20T10:30:00Z",
    "exercises": [
        {
            "title": "Bench Press",
            "primary_muscle_group": "Chest",
            "sets": [
                {"type": "warmup", "weight_kg": 60.0, "reps": 10, "rpe": None},
                {"type": "normal", "weight_kg": 100.0, "reps": 5, "rpe": 8.0},
                {"type": "normal", "weight_kg": 100.0, "reps": 5, "rpe": 8.5},
            ],
        }
    ],
}


def test_transform_workout_exercises_json():
    row = _transform_workout(_SAMPLE_WORKOUT)
    assert row["exercises_json"] is not None


def test_transform_workout_date():
    row = _transform_workout(_SAMPLE_WORKOUT)
    assert row["date"] == "2026-04-20"


def test_transform_workout_name():
    row = _transform_workout(_SAMPLE_WORKOUT)
    assert row["name"] == "Push Day"


def test_transform_workout_duration():
    row = _transform_workout(_SAMPLE_WORKOUT)
    # 90 minutes = 5400 seconds
    assert row["moving_time_s"] == 5400


def test_transform_workout_hevy_workout_id():
    row = _transform_workout(_SAMPLE_WORKOUT)
    assert row["hevy_workout_id"] == _SAMPLE_WORKOUT["id"]


def test_transform_workout_volume():
    row = _transform_workout(_SAMPLE_WORKOUT)
    # 2 normal sets × 5 reps × 100 kg = 1000 kg (warmup excluded)
    assert row["total_volume_kg"] == pytest.approx(1000.0)


def test_transform_workout_sets():
    row = _transform_workout(_SAMPLE_WORKOUT)
    assert row["total_sets"] == 2  # warmup excluded


def test_transform_workout_stable_id():
    row1 = _transform_workout(_SAMPLE_WORKOUT)
    row2 = _transform_workout(_SAMPLE_WORKOUT)
    assert row1["id"] == row2["id"]


# ── compute_hevy_metrics ──────────────────────────────────────────────────────


def _make_exercises_json(**overrides):
    exercises = [
        {
            "title": "Squat",
            "primary_muscle_group": "Quads",
            "sets": [
                {"type": "warmup", "weight_kg": 60.0, "reps": 8, "rpe": None},
                {"type": "normal", "weight_kg": 120.0, "reps": 5, "rpe": 8.0},
                {"type": "normal", "weight_kg": 120.0, "reps": 5, "rpe": 8.5},
                {"type": "normal", "weight_kg": 120.0, "reps": 4, "rpe": 9.0},
            ],
        }
    ]
    return json.dumps(exercises)


def test_compute_hevy_metrics_volume():
    metrics = compute_hevy_metrics(_make_exercises_json())
    # 3 normal sets: 5×120 + 5×120 + 4×120 = 1680 kg
    assert metrics["total_volume_kg"] == pytest.approx(1680.0)


def test_compute_hevy_metrics_sets():
    metrics = compute_hevy_metrics(_make_exercises_json())
    assert metrics["total_sets"] == 3


def test_compute_hevy_metrics_avg_rpe():
    metrics = compute_hevy_metrics(_make_exercises_json())
    # avg of 8.0, 8.5, 9.0 = 8.5
    assert metrics["avg_rpe"] == pytest.approx(8.5)


def test_compute_hevy_metrics_1rm_estimate():
    metrics = compute_hevy_metrics(_make_exercises_json())
    assert "Squat" in metrics["estimated_1rms"]
    # Best 1RM from 5 reps @ 120 kg: 120 * (1 + 5/30) = 140.0
    assert metrics["estimated_1rms"]["Squat"] == pytest.approx(140.0)


def test_compute_hevy_metrics_muscle_volume():
    metrics = compute_hevy_metrics(_make_exercises_json())
    assert "Quads" in metrics["muscle_volume"]


def test_compute_hevy_metrics_summary_contains_sets():
    metrics = compute_hevy_metrics(_make_exercises_json())
    assert "working sets" in metrics["analysis_summary"]


def test_compute_hevy_metrics_summary_contains_volume():
    metrics = compute_hevy_metrics(_make_exercises_json())
    assert "kg total volume" in metrics["analysis_summary"]


def test_compute_hevy_metrics_empty_json_returns_empty():
    assert compute_hevy_metrics(None) == {}
    assert compute_hevy_metrics("") == {}


def test_compute_hevy_metrics_invalid_json_returns_empty():
    assert compute_hevy_metrics("not-json") == {}


def test_compute_hevy_metrics_no_rpe_gives_none_avg():
    exercises = [
        {
            "title": "Deadlift",
            "primary_muscle_group": "Hamstrings",
            "sets": [{"type": "normal", "weight_kg": 150.0, "reps": 3, "rpe": None}],
        }
    ]
    metrics = compute_hevy_metrics(json.dumps(exercises))
    assert metrics["avg_rpe"] is None
