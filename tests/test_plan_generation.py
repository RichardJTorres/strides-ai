"""Unit tests for strides_ai.plan_generation."""

import json
from datetime import date

from strides_ai.plan_generation import (
    build_plan_generation_prompt,
    parse_plan_generation_response,
)

# ── build_plan_generation_prompt ────────────────────────────────────────────────


def test_prompt_includes_date_range():
    prompt = build_plan_generation_prompt(
        "cycling", "", [], {"races": [], "blocked_days": []}, [], [], "2026-10-01", "2026-10-14", ""
    )
    assert "2026-10-01" in prompt
    assert "2026-10-14" in prompt


def test_prompt_includes_current_date():
    """Regression test: without an explicit 'today' anchor, the model can't tell how
    long ago a logged activity happened and may misjudge recency (e.g. calling a
    two-week-old ride "Sunday's ride")."""
    prompt = build_plan_generation_prompt(
        "cycling", "", [], {"races": [], "blocked_days": []}, [], [], "2026-10-01", "2026-10-14", ""
    )
    assert "Current Date" in prompt
    assert date.today().isoformat() in prompt


def test_prompt_includes_freeform_text():
    prompt = build_plan_generation_prompt(
        "cycling",
        "",
        [],
        {"races": [], "blocked_days": []},
        [],
        [],
        "2026-10-01",
        "2026-10-14",
        "Focus on climbing, I have a century in November",
    )
    assert "Focus on climbing, I have a century in November" in prompt


def test_prompt_omits_freeform_section_when_blank():
    prompt = build_plan_generation_prompt(
        "cycling",
        "",
        [],
        {"races": [], "blocked_days": []},
        [],
        [],
        "2026-10-01",
        "2026-10-14",
        "  ",
    )
    assert "Athlete's Request" not in prompt


def test_prompt_includes_profile_text():
    prompt = build_plan_generation_prompt(
        "cycling",
        "## Athlete Profile\nFTP: 250w",
        [],
        {"races": [], "blocked_days": []},
        [],
        [],
        "2026-10-01",
        "2026-10-14",
        "",
    )
    assert "FTP: 250w" in prompt


def test_prompt_includes_memories():
    memories = [{"category": "goal", "content": "Century ride in November"}]
    prompt = build_plan_generation_prompt(
        "cycling",
        "",
        memories,
        {"races": [], "blocked_days": []},
        [],
        [],
        "2026-10-01",
        "2026-10-14",
        "",
    )
    assert "[goal] Century ride in November" in prompt


def test_prompt_includes_calendar_constraints():
    prefs = {
        "races": [{"date": "2026-11-15", "name": "Fall Century"}],
        "blocked_days": ["2026-10-05"],
    }
    prompt = build_plan_generation_prompt(
        "cycling", "", [], prefs, [], [], "2026-10-01", "2026-10-14", ""
    )
    assert "Fall Century" in prompt
    assert "2026-10-05" in prompt


def test_prompt_omits_calendar_constraints_when_empty():
    prompt = build_plan_generation_prompt(
        "cycling", "", [], {"races": [], "blocked_days": []}, [], [], "2026-10-01", "2026-10-14", ""
    )
    assert "Calendar Constraints" not in prompt


def test_prompt_includes_surrounding_plan():
    surrounding = [
        {
            "date": "2026-09-28",
            "workout_type": "Long Ride",
            "distance_km": 80,
            "duration_min": 180,
            "intensity": "moderate",
        }
    ]
    prompt = build_plan_generation_prompt(
        "cycling",
        "",
        [],
        {"races": [], "blocked_days": []},
        surrounding,
        [],
        "2026-10-01",
        "2026-10-14",
        "",
    )
    assert "Surrounding Training Blocks" in prompt
    assert "2026-09-28" in prompt
    assert "Long Ride" in prompt


def test_prompt_warns_surrounding_plan_is_not_confirmed_completed():
    """Regression test: the model conflated a future *planned* ride with a completed
    activity and described it in the past tense ("Sunday's ride")."""
    surrounding = [{"date": "2026-10-04", "workout_type": "Long Ride", "distance_km": 100}]
    prompt = build_plan_generation_prompt(
        "cycling",
        "",
        [],
        {"races": [], "blocked_days": []},
        surrounding,
        [],
        "2026-10-05",
        "2026-10-14",
        "",
    )
    assert "not confirmed completed" in prompt
    assert "past tense" in prompt


def test_prompt_omits_surrounding_section_when_empty():
    prompt = build_plan_generation_prompt(
        "cycling", "", [], {"races": [], "blocked_days": []}, [], [], "2026-10-01", "2026-10-14", ""
    )
    assert "Surrounding Training Blocks" not in prompt


def test_prompt_uses_mode_specific_system_prompt():
    from strides_ai.modes import CYCLING_SYSTEM_PROMPT

    prompt = build_plan_generation_prompt(
        "cycling", "", [], {"races": [], "blocked_days": []}, [], [], "2026-10-01", "2026-10-14", ""
    )
    assert CYCLING_SYSTEM_PROMPT in prompt


# ── parse_plan_generation_response ──────────────────────────────────────────────


def test_parse_returns_workouts_and_summary():
    raw = json.dumps(
        {
            "workouts": [{"date": "2026-10-02", "workout_type": "Easy Ride"}],
            "summary": "A light week to start.",
        }
    )
    result = parse_plan_generation_response(raw, "2026-10-01", "2026-10-14")
    assert result["workouts"] == [{"date": "2026-10-02", "workout_type": "Easy Ride"}]
    assert result["summary"] == "A light week to start."


def test_parse_strips_markdown_fences():
    raw = json.dumps({"workouts": [], "summary": "ok"})
    fenced = f"```json\n{raw}\n```"
    result = parse_plan_generation_response(fenced, "2026-10-01", "2026-10-14")
    assert result["summary"] == "ok"


def test_parse_drops_entries_missing_date():
    raw = json.dumps({"workouts": [{"workout_type": "Easy Ride"}], "summary": ""})
    result = parse_plan_generation_response(raw, "2026-10-01", "2026-10-14")
    assert result["workouts"] == []


def test_parse_drops_entries_missing_workout_type():
    raw = json.dumps({"workouts": [{"date": "2026-10-02"}], "summary": ""})
    result = parse_plan_generation_response(raw, "2026-10-01", "2026-10-14")
    assert result["workouts"] == []


def test_parse_drops_entries_outside_requested_range():
    raw = json.dumps(
        {
            "workouts": [
                {"date": "2026-09-20", "workout_type": "Easy Ride"},
                {"date": "2026-10-05", "workout_type": "Long Ride"},
                {"date": "2026-11-01", "workout_type": "Easy Ride"},
            ],
            "summary": "",
        }
    )
    result = parse_plan_generation_response(raw, "2026-10-01", "2026-10-14")
    assert result["workouts"] == [{"date": "2026-10-05", "workout_type": "Long Ride"}]


def test_parse_defaults_summary_to_empty_string():
    raw = json.dumps({"workouts": []})
    result = parse_plan_generation_response(raw, "2026-10-01", "2026-10-14")
    assert result["summary"] == ""
