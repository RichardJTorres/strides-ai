"""Unit tests for strides_ai.coach — pure formatting and assembly functions."""

from datetime import date, timedelta

import pytest

from strides_ai import db
from strides_ai.coach import (
    CYCLING_SYSTEM_PROMPT,
    HYBRID_SYSTEM_PROMPT,
    RUNNING_SYSTEM_PROMPT,
    _format_duration,
    _format_pace,
    _format_speed,
    build_initial_history,
    build_system,
    build_training_log,
)

# ── _format_pace ──────────────────────────────────────────────────────────────


def test_format_pace_none():
    assert _format_pace(None) == "—"


def test_format_pace_exact_minutes():
    assert _format_pace(360.0) == "6:00/km"


def test_format_pace_with_seconds():
    assert _format_pace(375.0) == "6:15/km"


def test_format_pace_sub_minute():
    assert _format_pace(55.0) == "0:55/km"


def test_format_pace_zero():
    assert _format_pace(0.0) == "0:00/km"


def test_format_pace_rounds_down():
    # 361.9 → 6:01 (int truncation, not rounding)
    assert _format_pace(361.9) == "6:01/km"


# ── _format_duration ──────────────────────────────────────────────────────────


def test_format_duration_none():
    assert _format_duration(None) == "—"


def test_format_duration_zero():
    assert _format_duration(0) == "0m00s"


def test_format_duration_seconds_only():
    assert _format_duration(45) == "0m45s"


def test_format_duration_minutes():
    assert _format_duration(125) == "2m05s"


def test_format_duration_one_hour():
    assert _format_duration(3600) == "1h00m00s"


def test_format_duration_hours_and_minutes():
    assert _format_duration(5400) == "1h30m00s"


def test_format_duration_full():
    assert _format_duration(3723) == "1h02m03s"


# ── build_system ──────────────────────────────────────────────────────────────


def test_build_system_no_profile_no_memories(tmp_db):
    result = build_system("", [])
    assert RUNNING_SYSTEM_PROMPT in result
    assert "## Recent Activities" in result


def test_build_system_with_profile(tmp_db):
    result = build_system("Athlete profile text", [])
    assert "Athlete profile text" in result
    assert RUNNING_SYSTEM_PROMPT in result


def test_build_system_with_memories(tmp_db):
    memories = [
        {"category": "goal", "content": "BQ in fall 2025"},
        {"category": "injury", "content": "Right knee tendinitis"},
    ]
    result = build_system("", memories)
    assert "Coaching Notes" in result
    assert "[goal] BQ in fall 2025" in result
    assert "[injury] Right knee tendinitis" in result


def test_build_system_with_profile_and_memories(tmp_db):
    result = build_system("Profile here", [{"category": "pref", "content": "no speed work"}])
    assert "Profile here" in result
    assert "[pref] no speed work" in result


def test_build_system_empty_memories_list(tmp_db):
    result = build_system("profile", [])
    assert "Coaching Notes" not in result


def test_build_system_injects_upcoming_workouts(tmp_db):
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    db.save_planned_workout(tomorrow, "Long Run", None, 20.0, None, 120, "easy")
    result = build_system("", [])
    assert "Upcoming Planned Workouts" in result
    assert "Long Run" in result
    assert tomorrow in result


def test_build_system_no_upcoming_workouts_section_when_empty(tmp_db):
    result = build_system("", [])
    assert "Upcoming Planned Workouts" not in result


def test_build_system_embeds_recent_activities(tmp_db):
    rows = [_make_row()]
    result = build_system("", [], activities=rows)
    assert "## Recent Activities" in result
    assert "Morning Run" in result  # name from _make_row


# ── build_training_log ────────────────────────────────────────────────────────


def _make_row(
    date="2025-06-15",
    name="Morning Run",
    distance_m=10000,
    moving_time_s=3600,
    avg_pace_s_per_km=360.0,
    avg_hr=145,
    max_hr=165,
    avg_cadence=174,
    elevation_gain_m=50,
    suffer_score=42,
    perceived_exertion=5.0,
    sport_type="Run",
):
    """Return a dict that behaves like sqlite3.Row for build_training_log."""
    return {
        "date": date,
        "name": name,
        "distance_m": distance_m,
        "moving_time_s": moving_time_s,
        "avg_pace_s_per_km": avg_pace_s_per_km,
        "avg_hr": avg_hr,
        "max_hr": max_hr,
        "avg_cadence": avg_cadence,
        "elevation_gain_m": elevation_gain_m,
        "suffer_score": suffer_score,
        "perceived_exertion": perceived_exertion,
        "sport_type": sport_type,
    }


def test_build_training_log_empty():
    assert build_training_log([]) == "No activities found."


def test_build_training_log_single_run_contains_date():
    log = build_training_log([_make_row(date="2025-06-15")])
    assert "2025-06-15" in log


def test_build_training_log_single_run_contains_name():
    log = build_training_log([_make_row(name="Evening Jog")])
    assert "Evening Jog" in log


def test_build_training_log_distance_in_km():
    log = build_training_log([_make_row(distance_m=10_000)])
    assert "10.00" in log


def test_build_training_log_pace_formatted():
    log = build_training_log([_make_row(avg_pace_s_per_km=360.0)])
    assert "6:00/km" in log


def test_build_training_log_duration_formatted():
    log = build_training_log([_make_row(moving_time_s=3600)])
    assert "1h00m00s" in log


def test_build_training_log_totals_line():
    rows = [_make_row(distance_m=10_000), _make_row(distance_m=5_000)]
    log = build_training_log(rows)
    assert "2 runs" in log
    assert "15.0 km" in log


def test_build_training_log_none_fields_show_dash():
    row = _make_row(
        avg_hr=None,
        max_hr=None,
        avg_cadence=None,
        elevation_gain_m=None,
        suffer_score=None,
        perceived_exertion=None,
    )
    log = build_training_log([row])
    assert "—" in log


# ── build_initial_history ─────────────────────────────────────────────────────


def test_build_initial_history_structure():
    rows = [_make_row()]
    history = build_initial_history(rows, [])
    # First two messages are the log injection exchange
    assert history[0]["role"] == "user"
    assert history[1]["role"] == "assistant"
    assert "training log" in history[0]["content"].lower()


def test_build_initial_history_empty_activities():
    history = build_initial_history([], [])
    assert "No activities found" in history[0]["content"]


def test_build_initial_history_activity_count_in_reply():
    rows = [_make_row(), _make_row()]
    history = build_initial_history(rows, [])
    assert "2 runs" in history[1]["content"]


def test_build_initial_history_includes_prior_messages():
    prior = [
        {"role": "user", "content": "How was my last run?"},
        {"role": "assistant", "content": "Great effort!"},
    ]
    history = build_initial_history([], prior)
    assert len(history) == 4  # 2 seed + 2 prior
    assert history[2]["content"] == "How was my last run?"
    assert history[3]["content"] == "Great effort!"


def test_build_initial_history_cycling_label():
    history = build_initial_history([_make_row(sport_type="Ride")], [], mode="cycling")
    assert "rides" in history[1]["content"]


def test_build_initial_history_hybrid_label():
    rows = [_make_row(sport_type="Run"), _make_row(sport_type="Ride")]
    history = build_initial_history(rows, [], mode="hybrid")
    assert "activities" in history[1]["content"]


# ── _format_speed ─────────────────────────────────────────────────────────────


def test_format_speed_none():
    assert _format_speed(None) == "—"


def test_format_speed_zero():
    assert _format_speed(0.0) == "—"


def test_format_speed_negative():
    assert _format_speed(-1.0) == "—"


def test_format_speed_normal():
    # 360 s/km → 3600 / 360 = 10.0 km/h
    assert _format_speed(360.0) == "10.0km/h"


def test_format_speed_fast():
    # 180 s/km → 20.0 km/h
    assert _format_speed(180.0) == "20.0km/h"


# ── build_system mode variants ────────────────────────────────────────────────


def test_build_system_cycling_mode(tmp_db):
    result = build_system("", [], mode="cycling")
    assert CYCLING_SYSTEM_PROMPT in result
    assert "## Recent Activities" in result


def test_build_system_hybrid_mode(tmp_db):
    result = build_system("", [], mode="hybrid")
    assert HYBRID_SYSTEM_PROMPT in result
    assert "## Recent Activities" in result


def test_build_system_invalid_mode_falls_back_to_running(tmp_db):
    result = build_system("", [], mode="triathlon")
    assert RUNNING_SYSTEM_PROMPT in result
    assert "## Recent Activities" in result


# ── build_training_log cycling and hybrid modes ───────────────────────────────


def test_build_training_log_cycling_header():
    log = build_training_log([_make_row(sport_type="Ride")], mode="cycling")
    header = log.split("\n")[0]
    assert "SPEED" in header
    # Running-specific label should not be in the cycling header
    assert "PACE" not in header


def test_build_training_log_cycling_totals():
    rows = [_make_row(sport_type="Ride"), _make_row(sport_type="Ride")]
    log = build_training_log(rows, mode="cycling")
    assert "2 rides" in log


def test_build_training_log_hybrid_totals():
    rows = [_make_row(sport_type="Run"), _make_row(sport_type="Ride")]
    log = build_training_log(rows, mode="hybrid")
    assert "2 activities" in log


def test_build_training_log_hybrid_header_has_type_column():
    log = build_training_log([_make_row()], mode="hybrid")
    header = log.split("\n")[0]
    assert "TYPE" in header
