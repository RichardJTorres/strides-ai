"""Unit tests for strides_ai.route_analysis."""

import json

from strides_ai.route_analysis import (
    build_route_analysis_prompt,
    parse_route_analysis_response,
)

SAMPLE_WORKOUT = {
    "workout_type": "Easy Ride",
    "intensity": "easy",
    "distance_km": 30.0,
    "duration_min": 90,
    "description": "Recovery spin, keep it conversational",
}

SAMPLE_ROUTE_SUMMARY = {
    "name": "Walnut - Via Verde",
    "distance_m": 45595.8,
    "elevation_gain_m": 712.0,
    "elevation_loss_m": 714.0,
    "terrain": "climbing",
    "difficulty": "moderate",
    "surface": "paved",
    "unpaved_pct": 0,
}

SAMPLE_PROFILE = [
    {"distance_km": 0.0, "elevation_m": 100.0, "grade_pct": None},
    {"distance_km": 1.0, "elevation_m": 150.0, "grade_pct": 5.0},
]


# ── build_route_analysis_prompt ─────────────────────────────────────────────


def test_prompt_includes_workout_goal():
    prompt = build_route_analysis_prompt(SAMPLE_WORKOUT, SAMPLE_ROUTE_SUMMARY, [], "")
    assert "Easy Ride" in prompt
    assert "Recovery spin, keep it conversational" in prompt
    assert "30.0 km" in prompt


def test_prompt_includes_route_stats():
    prompt = build_route_analysis_prompt(SAMPLE_WORKOUT, SAMPLE_ROUTE_SUMMARY, [], "")
    assert "Walnut - Via Verde" in prompt
    assert "45.6 km" in prompt
    assert "712" in prompt
    assert "climbing" in prompt


def test_prompt_includes_elevation_profile_when_present():
    prompt = build_route_analysis_prompt(SAMPLE_WORKOUT, SAMPLE_ROUTE_SUMMARY, SAMPLE_PROFILE, "")
    assert "Elevation Profile" in prompt
    assert "5.0" in prompt


def test_prompt_omits_elevation_profile_when_empty():
    prompt = build_route_analysis_prompt(SAMPLE_WORKOUT, SAMPLE_ROUTE_SUMMARY, [], "")
    assert "Elevation Profile" not in prompt


def test_prompt_includes_profile_text_when_present():
    prompt = build_route_analysis_prompt(
        SAMPLE_WORKOUT, SAMPLE_ROUTE_SUMMARY, [], "## Athlete Profile\nFTP: 250w"
    )
    assert "FTP: 250w" in prompt


def test_prompt_handles_missing_optional_workout_fields():
    minimal = {"workout_type": "Easy Ride", "intensity": "easy"}
    prompt = build_route_analysis_prompt(minimal, SAMPLE_ROUTE_SUMMARY, [], "")
    assert "not specified" in prompt


# ── parse_route_analysis_response ───────────────────────────────────────────


def test_parse_returns_all_fields():
    raw = json.dumps(
        {
            "verdict": "too_hard",
            "explanation": "Too much climbing for a recovery day.",
            "suggestion": "Pick a flatter route.",
        }
    )
    result = parse_route_analysis_response(raw)
    assert result == {
        "verdict": "too_hard",
        "explanation": "Too much climbing for a recovery day.",
        "suggestion": "Pick a flatter route.",
    }


def test_parse_strips_markdown_fences():
    raw = json.dumps({"verdict": "good_match", "explanation": "Fits well.", "suggestion": None})
    fenced = f"```json\n{raw}\n```"
    result = parse_route_analysis_response(fenced)
    assert result["verdict"] == "good_match"


def test_parse_defaults_missing_verdict_to_needs_info():
    raw = json.dumps({"explanation": "Not enough info."})
    result = parse_route_analysis_response(raw)
    assert result["verdict"] == "needs_info"


def test_parse_defaults_missing_suggestion_to_none():
    raw = json.dumps({"verdict": "good_match", "explanation": "Fits well."})
    result = parse_route_analysis_response(raw)
    assert result["suggestion"] is None
