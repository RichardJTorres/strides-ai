"""Unit tests for strides_ai.schedule.analyze_nutrition."""

import json

import pytest

from strides_ai.schedule import NUTRITION_SYSTEM_PROMPT, analyze_nutrition, parse_nutrition_response

SAMPLE_WORKOUT = {
    "workout_type": "Long Run",
    "intensity": "easy",
    "distance_km": 20.0,
    "elevation_m": 300.0,
    "duration_min": 120,
    "description": "Easy long run in the hills",
}

SAMPLE_NUTRITION = {
    "calories_pre": 400,
    "calories_during": 200,
    "calories_post": 500,
    "hydration_pre_ml": 500,
    "hydration_during_ml": 750,
    "hydration_post_ml": 500,
    "notes": "Eat well before this long run.",
}


class FakeBackend:
    """Records the one-shot call nutrition makes; whichever provider is selected sits here."""

    def __init__(self, reply: str):
        self.reply = reply
        self.calls = []

    def stateless_turn(self, system, user_input, on_token, source="other"):
        self.calls.append({"system": system, "user_input": user_input, "source": source})
        return self.reply


def test_returns_parsed_dict():
    result = analyze_nutrition(
        SAMPLE_WORKOUT, "Athlete profile", FakeBackend(json.dumps(SAMPLE_NUTRITION))
    )
    assert result == SAMPLE_NUTRITION


def test_uses_selected_backend_and_logs_as_nutrition():
    backend = FakeBackend(json.dumps(SAMPLE_NUTRITION))
    analyze_nutrition(SAMPLE_WORKOUT, "Runner since 2010", backend)
    (call,) = backend.calls
    assert call["system"] == NUTRITION_SYSTEM_PROMPT
    assert call["source"] == "nutrition"
    assert "Runner since 2010" in call["user_input"]
    assert "300" in call["user_input"]  # elevation_m from SAMPLE_WORKOUT


def test_missing_optional_fields_shows_not_specified():
    backend = FakeBackend(json.dumps(SAMPLE_NUTRITION))
    result = analyze_nutrition({"workout_type": "Easy Run", "intensity": "easy"}, "", backend)
    assert "calories_pre" in result
    assert "not specified" in backend.calls[0]["user_input"]


@pytest.mark.parametrize(
    "reply",
    [
        f"```json\n{json.dumps(SAMPLE_NUTRITION)}\n```",
        f"Here are your targets:\n{json.dumps(SAMPLE_NUTRITION)}\nGood luck!",
    ],
)
def test_parse_tolerates_fences_and_surrounding_prose(reply):
    assert parse_nutrition_response(reply) == SAMPLE_NUTRITION


def test_parse_rejects_reply_without_json():
    with pytest.raises(json.JSONDecodeError):
        parse_nutrition_response("Sorry, I can't help with that.")
