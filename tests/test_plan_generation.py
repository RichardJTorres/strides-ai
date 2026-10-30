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
    assert result["workouts"] == [
        {"date": "2026-10-02", "workout_type": "Easy Ride", "structure": None}
    ]
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
    assert result["workouts"] == [
        {"date": "2026-10-05", "workout_type": "Long Ride", "structure": None}
    ]


def test_parse_defaults_summary_to_empty_string():
    raw = json.dumps({"workouts": []})
    result = parse_plan_generation_response(raw, "2026-10-01", "2026-10-14")
    assert result["summary"] == ""


INDOOR_STRUCTURE = {
    "blocks": [
        {"kind": "warmup", "duration_s": 600, "from_pct": 0.5, "to_pct": 0.75},
        {
            "kind": "intervals",
            "repeat": 4,
            "on_s": 240,
            "on_pct": 1.05,
            "off_s": 180,
            "off_pct": 0.55,
        },
        {"kind": "cooldown", "duration_s": 300, "from_pct": 0.7, "to_pct": 0.45},
    ]
}


def test_parse_keeps_valid_structure_and_derives_duration():
    raw = json.dumps(
        {
            "workouts": [
                {
                    "date": "2026-10-02",
                    "workout_type": "Indoor Ride",
                    "distance": 30,
                    "elevation": 450,
                    "duration_min": 999,
                    "structure": INDOOR_STRUCTURE,
                }
            ]
        }
    )
    w = parse_plan_generation_response(raw, "2026-10-01", "2026-10-14")["workouts"][0]
    assert w["structure"] == INDOOR_STRUCTURE
    assert w["duration_min"] == 10 + 28 + 5  # 600s + 4*(240+180)s + 300s = 2580s = 43 min
    assert w["distance_km"] == 30 and w["elevation_m"] == 450


def test_parse_strips_structure_from_non_cycling_types():
    raw = json.dumps(
        {
            "workouts": [
                {"date": "2026-10-02", "workout_type": "Easy Run", "structure": INDOOR_STRUCTURE}
            ]
        }
    )
    w = parse_plan_generation_response(raw, "2026-10-01", "2026-10-14")["workouts"][0]
    assert w["structure"] is None


def test_plan_table_shows_elevation_and_structure():
    from strides_ai.plan_generation import _plan_table
    from strides_ai.workout_structure import structure_to_json

    table = _plan_table(
        [
            {
                "date": "2026-10-02",
                "workout_type": "Indoor Ride",
                "distance_km": 30,
                "elevation_m": 450,
                "duration_min": 43,
                "intensity": "hard",
                "structure_json": structure_to_json(INDOOR_STRUCTURE),
            }
        ]
    )
    assert "450 m" in table
    assert "4×(4:00 @ 105%, 3:00 @ 55%)" in table
