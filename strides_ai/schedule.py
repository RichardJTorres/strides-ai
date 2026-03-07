"""Nutrition analysis for planned workouts."""

import json
import os
import re

import anthropic
import httpx

from .backends.ollama import DEFAULT_HOST

NUTRITION_SYSTEM_PROMPT = """\
You are a sports nutritionist. Analyze the described workout and return structured nutrition recommendations.
You must respond with ONLY a valid JSON object — no prose, no markdown fences, no explanation.
The object must have exactly these keys:
  "calories_pre"        – integer, kcal to consume 1-2 hours before the workout
  "calories_during"     – integer, kcal to consume during the workout (0 if short/easy)
  "calories_post"       – integer, kcal to consume within 30-60 minutes after
  "hydration_pre_ml"   – integer, ml of fluid to drink 1-2 hours before
  "hydration_during_ml" – integer, ml of fluid to drink during the workout
  "hydration_post_ml"  – integer, ml of fluid to drink after
  "notes"               – string, 2-3 sentences of practical advice tailored to this specific workout\
"""


def _build_prompt(workout: dict, profile_text: str) -> str:
    dist = f"{workout['distance_km']} km" if workout.get("distance_km") else "not specified"
    elev = f"{workout['elevation_m']} m" if workout.get("elevation_m") else "not specified"
    dur = f"{workout['duration_min']} minutes" if workout.get("duration_min") else "not specified"
    return f"""\
Workout type: {workout.get("workout_type", "Unknown")}
Intensity: {workout.get("intensity", "unknown")}
Distance: {dist}
Elevation gain: {elev}
Duration: {dur}
Notes: {workout.get("description") or "none"}

Athlete profile:
{profile_text or "No profile provided."}"""


def analyze_nutrition(workout: dict, profile_text: str, api_key: str) -> dict:
    """Generate nutrition recommendations for a planned workout.

    Routes to Ollama when PROVIDER=ollama, otherwise uses Claude Haiku.
    """
    provider = os.environ.get("PROVIDER", "claude").lower()
    prompt = _build_prompt(workout, profile_text)

    if provider == "ollama":
        model = os.environ.get("OLLAMA_MODEL", "llama3.1")
        host = os.environ.get("OLLAMA_HOST", DEFAULT_HOST)
        response = httpx.post(
            f"{host}/api/chat",
            json={
                "model": model,
                "stream": False,
                "format": "json",
                "messages": [
                    {"role": "system", "content": NUTRITION_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
            },
            timeout=60,
        )
        response.raise_for_status()
        text = response.json()["message"]["content"].strip()
    else:
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=512,
            system=NUTRITION_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text.strip()
        text = re.sub(r"^```[a-z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)

    return json.loads(text)
