"""The unit_system setting cascades to every LLM-facing surface; stored data stays SI."""

import pytest

from strides_ai.activity_context import build_activity_card
from strides_ai.analysis import build_analysis_summary, render_analysis_summary
from strides_ai.backends.base import _workout_measurements
from strides_ai.coach import build_system, build_training_log, older_activity_summary
from strides_ai.compliance import (
    ComplianceActivity,
    ComplianceStatus,
    PlannedWorkout,
    compute_day_compliance,
)
from strides_ai.modes import MODES
from strides_ai.plan_generation import parse_plan_generation_response, plan_generation_system_prompt
from strides_ai.units import UnitSystem

M, I = UnitSystem.METRIC, UnitSystem.IMPERIAL


def _run(**overrides):
    row = {
        "id": 1,
        "date": "2025-06-15",
        "name": "Morning Run",
        "distance_m": 16093.44,  # 10 mi
        "moving_time_s": 4800,
        "avg_pace_s_per_km": 300.0,
        "avg_hr": 145,
        "max_hr": 165,
        "avg_cadence": 174,
        "elevation_gain_m": 100.0,
        "suffer_score": 42,
        "perceived_exertion": 5.0,
        "sport_type": "Run",
    }
    row.update(overrides)
    return row


# ── System prompt ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize("mode", list(MODES))
def test_mode_prompts_no_longer_hardcode_metric(mode):
    assert "metric units" not in MODES[mode].system_prompt


@pytest.mark.parametrize("system,expected", [(M, "METRIC"), (I, "IMPERIAL")])
def test_build_system_states_unit_system(tmp_db, system, expected):
    result = str(build_system("", [], units=system))
    assert f"The athlete uses the {expected} system" in result
    assert "Earlier messages in this conversation may use a different unit system" in result


def test_build_system_defaults_to_metric(tmp_db):
    assert "The athlete uses the METRIC system" in str(build_system("", []))


def test_build_system_activity_log_uses_selected_units(tmp_db):
    result = str(build_system("", [], activities=[_run()], units=I))
    assert "DIST(mi)" in result
    assert "10.00" in result
    assert "8:02/mi" in result


# ── Training log ───────────────────────────────────────────────────────────────


def test_training_log_imperial_running():
    log = build_training_log([_run()], "running", I)
    assert "DIST(mi)" in log and "ELEV(ft)" in log
    assert "8:02/mi" in log
    assert "328" in log  # 100 m of climbing
    assert "Total: 1 runs, 10.0 mi" in log


def test_training_log_metric_running():
    log = build_training_log([_run()], "running", M)
    assert "DIST(km)" in log and "ELEV(m)" in log
    assert "16.09" in log
    assert "5:00/km" in log


def test_training_log_imperial_cycling_speed():
    log = build_training_log([_run(sport_type="Ride", avg_pace_s_per_km=120.0)], "cycling", I)
    assert "18.6 mph" in log


def test_training_log_imperial_lifting_volume():
    row = _run(sport_type="WeightTraining", total_volume_kg=1000.0, total_sets=12)
    log = build_training_log([row], "lifting", I)
    assert "VOLUME(lb)" in log
    assert "2205" in log
    assert "lb cumulative volume" in log


def test_older_activity_summary_uses_selected_units():
    from datetime import date

    text = older_activity_summary([_run(date="2025-01-15")], date(2025, 6, 15), units=I)
    assert "distance_mi=10.00" in text
    assert "elevation_ft=328.08" in text


# ── Analysis summary is re-rendered on read ────────────────────────────────────


def test_analysis_summary_imperial():
    metrics = {"pace_fade_s_per_km": 20.0, "high_elevation_flag": 1, "climb_m_per_km": 25.0}
    text = build_analysis_summary(metrics, I)
    assert "Positive pace fade of 32 s/mi" in text
    assert "Hilly course (132 ft/mi elevation gain)" in text


def test_render_summary_rebuilds_completed_analysis_in_current_units():
    row = _run(
        analysis_status="done",
        analysis_summary="Positive pace fade of 20 s/km in final third.",
        pace_fade_s_per_km=20.0,
    )
    assert "s/mi" in render_analysis_summary(row, I)
    assert "s/km" in render_analysis_summary(row, M)


def test_render_summary_keeps_stored_text_when_not_done():
    row = _run(analysis_status="skipped", analysis_summary="Manual activity")
    assert render_analysis_summary(row, I) == "Manual activity"


def test_activity_card_imperial():
    card = build_activity_card(_run(pace_fade_s_per_km=10.0, climb_m_per_km=20.0), I)
    assert "Distance: 10.00 mi" in card
    assert "Pace: 8:02/mi" in card
    assert "Elevation gain: 328 ft" in card
    assert "pace fade +16 s/mi" in card
    assert "climbing ratio 106 ft/mi" in card


# ── Compliance notes ─────────────────────────────────────────────────────────────


def test_compliance_shortfall_note_uses_selected_units():
    from datetime import date

    planned = PlannedWorkout(date=date(2025, 6, 15), workout_type="Long Run", distance_km=16.09344)
    act = ComplianceActivity(id=1, date=date(2025, 6, 15), sport_type="Run", distance_m=8046.72)
    day = compute_day_compliance(planned, [act], date(2025, 6, 20), I)
    assert day.status is ComplianceStatus.MODIFIED
    assert "5.0 mi vs planned 10.0 mi" in day.note
    # Stored/returned distances stay in km.
    assert day.planned_distance_km == pytest.approx(16.09344)


# ── LLM input is normalized to SI ─────────────────────────────────────────────────


def test_tool_workout_in_miles_is_stored_in_km():
    assert _workout_measurements(
        {"distance": 5, "distance_unit": "mi", "elevation": 328.084, "elevation_unit": "ft"}
    ) == (pytest.approx(8.05), 100)


def test_tool_workout_in_km_is_stored_as_is():
    assert _workout_measurements({"distance": 10, "distance_unit": "km"}) == (10.0, None)


def test_tool_workout_legacy_keys_still_work():
    assert _workout_measurements({"distance_km": 12, "elevation_m": 50}) == (12, 50)


def test_plan_generation_prompt_asks_for_selected_units():
    assert "in mi" in plan_generation_system_prompt(I)
    assert "in ft" in plan_generation_system_prompt(I)
    assert "in km" in plan_generation_system_prompt(M)


def test_plan_generation_response_normalizes_to_km():
    text = (
        '{"workouts": [{"date": "2026-10-20", "workout_type": "Long Run", '
        '"distance": 10, "elevation": 500}], "summary": "ok"}'
    )
    w = parse_plan_generation_response(text, "2026-10-19", "2026-10-25", I)["workouts"][0]
    assert w["distance_km"] == pytest.approx(16.09)
    assert w["elevation_m"] == 152
    assert "distance" not in w and "elevation" not in w
