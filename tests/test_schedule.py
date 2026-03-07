"""Unit tests for strides_ai.schedule.analyze_nutrition."""

import json
from unittest.mock import MagicMock, patch

import pytest

from strides_ai.schedule import analyze_nutrition

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


# ── Claude provider ────────────────────────────────────────────────────────────


def test_analyze_nutrition_claude_returns_parsed_dict(monkeypatch):
    monkeypatch.setenv("PROVIDER", "claude")
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=json.dumps(SAMPLE_NUTRITION))]

    with patch("strides_ai.schedule.anthropic.Anthropic") as MockClient:
        MockClient.return_value.messages.create.return_value = mock_response
        result = analyze_nutrition(SAMPLE_WORKOUT, "Athlete profile", "fake-key")

    assert result["calories_pre"] == 400
    assert result["calories_during"] == 200
    assert result["calories_post"] == 500
    assert result["hydration_pre_ml"] == 500
    assert result["hydration_during_ml"] == 750
    assert result["hydration_post_ml"] == 500
    assert result["notes"] == "Eat well before this long run."


def test_analyze_nutrition_claude_strips_markdown_fences(monkeypatch):
    """Claude may wrap JSON in ```json ... ``` — these must be stripped."""
    monkeypatch.setenv("PROVIDER", "claude")
    fenced = f"```json\n{json.dumps(SAMPLE_NUTRITION)}\n```"
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=fenced)]

    with patch("strides_ai.schedule.anthropic.Anthropic") as MockClient:
        MockClient.return_value.messages.create.return_value = mock_response
        result = analyze_nutrition(SAMPLE_WORKOUT, "", "fake-key")

    assert result["calories_pre"] == 400


def test_analyze_nutrition_claude_uses_haiku_model(monkeypatch):
    monkeypatch.setenv("PROVIDER", "claude")
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=json.dumps(SAMPLE_NUTRITION))]

    with patch("strides_ai.schedule.anthropic.Anthropic") as MockClient:
        mock_create = MockClient.return_value.messages.create
        mock_create.return_value = mock_response
        analyze_nutrition(SAMPLE_WORKOUT, "", "fake-key")

    _, kwargs = mock_create.call_args
    assert "haiku" in kwargs["model"]


def test_analyze_nutrition_claude_prompt_includes_elevation(monkeypatch):
    monkeypatch.setenv("PROVIDER", "claude")
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=json.dumps(SAMPLE_NUTRITION))]

    with patch("strides_ai.schedule.anthropic.Anthropic") as MockClient:
        mock_create = MockClient.return_value.messages.create
        mock_create.return_value = mock_response
        analyze_nutrition(SAMPLE_WORKOUT, "", "fake-key")

    _, kwargs = mock_create.call_args
    user_content = kwargs["messages"][0]["content"]
    assert "300" in user_content  # elevation_m from SAMPLE_WORKOUT


def test_analyze_nutrition_claude_prompt_includes_profile(monkeypatch):
    monkeypatch.setenv("PROVIDER", "claude")
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=json.dumps(SAMPLE_NUTRITION))]

    with patch("strides_ai.schedule.anthropic.Anthropic") as MockClient:
        mock_create = MockClient.return_value.messages.create
        mock_create.return_value = mock_response
        analyze_nutrition(SAMPLE_WORKOUT, "Runner since 2010", "fake-key")

    _, kwargs = mock_create.call_args
    user_content = kwargs["messages"][0]["content"]
    assert "Runner since 2010" in user_content


# ── Ollama provider ────────────────────────────────────────────────────────────


def test_analyze_nutrition_ollama_returns_parsed_dict(monkeypatch):
    monkeypatch.setenv("PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_MODEL", "llama3.1")

    mock_response = MagicMock()
    mock_response.json.return_value = {"message": {"content": json.dumps(SAMPLE_NUTRITION)}}
    mock_response.raise_for_status = MagicMock()

    with patch("strides_ai.schedule.httpx.post", return_value=mock_response):
        result = analyze_nutrition(SAMPLE_WORKOUT, "Athlete profile", "")

    assert result["calories_pre"] == 400
    assert result["hydration_during_ml"] == 750


def test_analyze_nutrition_ollama_uses_json_format(monkeypatch):
    monkeypatch.setenv("PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_MODEL", "llama3.1")

    mock_response = MagicMock()
    mock_response.json.return_value = {"message": {"content": json.dumps(SAMPLE_NUTRITION)}}
    mock_response.raise_for_status = MagicMock()

    with patch("strides_ai.schedule.httpx.post", return_value=mock_response) as mock_post:
        analyze_nutrition(SAMPLE_WORKOUT, "", "")

    _, kwargs = mock_post.call_args
    assert kwargs["json"]["format"] == "json"
    assert kwargs["json"]["stream"] is False


def test_analyze_nutrition_ollama_uses_configured_model(monkeypatch):
    monkeypatch.setenv("PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_MODEL", "mistral-nemo")

    mock_response = MagicMock()
    mock_response.json.return_value = {"message": {"content": json.dumps(SAMPLE_NUTRITION)}}
    mock_response.raise_for_status = MagicMock()

    with patch("strides_ai.schedule.httpx.post", return_value=mock_response) as mock_post:
        analyze_nutrition(SAMPLE_WORKOUT, "", "")

    _, kwargs = mock_post.call_args
    assert kwargs["json"]["model"] == "mistral-nemo"


def test_analyze_nutrition_ollama_sends_system_prompt(monkeypatch):
    monkeypatch.setenv("PROVIDER", "ollama")

    mock_response = MagicMock()
    mock_response.json.return_value = {"message": {"content": json.dumps(SAMPLE_NUTRITION)}}
    mock_response.raise_for_status = MagicMock()

    with patch("strides_ai.schedule.httpx.post", return_value=mock_response) as mock_post:
        analyze_nutrition(SAMPLE_WORKOUT, "", "")

    _, kwargs = mock_post.call_args
    messages = kwargs["json"]["messages"]
    roles = [m["role"] for m in messages]
    assert "system" in roles


# ── Shared behaviour ───────────────────────────────────────────────────────────


def test_analyze_nutrition_missing_optional_fields_does_not_crash(monkeypatch):
    """Workout with no distance/elevation/duration should not raise."""
    monkeypatch.setenv("PROVIDER", "claude")
    minimal_workout = {"workout_type": "Easy Run", "intensity": "easy"}
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=json.dumps(SAMPLE_NUTRITION))]

    with patch("strides_ai.schedule.anthropic.Anthropic") as MockClient:
        MockClient.return_value.messages.create.return_value = mock_response
        result = analyze_nutrition(minimal_workout, "", "fake-key")

    assert "calories_pre" in result


def test_analyze_nutrition_missing_optional_fields_shows_not_specified(monkeypatch):
    """'not specified' should appear in the prompt when fields are absent."""
    monkeypatch.setenv("PROVIDER", "claude")
    minimal_workout = {"workout_type": "Easy Run", "intensity": "easy"}
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=json.dumps(SAMPLE_NUTRITION))]

    with patch("strides_ai.schedule.anthropic.Anthropic") as MockClient:
        mock_create = MockClient.return_value.messages.create
        mock_create.return_value = mock_response
        analyze_nutrition(minimal_workout, "", "fake-key")

    _, kwargs = mock_create.call_args
    user_content = kwargs["messages"][0]["content"]
    assert "not specified" in user_content
