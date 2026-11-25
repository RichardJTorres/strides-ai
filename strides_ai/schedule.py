"""Nutrition analysis for planned workouts."""

import json
import re

from .db.models import PlanRow
from .units import DEFAULT_UNIT_SYSTEM, UnitSystem, describe_for_prompt

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


def _build_prompt(workout: dict, profile_text: str, units: UnitSystem = DEFAULT_UNIT_SYSTEM) -> str:
    def measured(field: str) -> str:
        m = PlanRow.measure_field(workout, field, units) if workout.get(field) else None
        return m.formatted if m else "not specified"

    dist = measured("distance_km")
    elev = measured("elevation_m")
    dur = f"{workout['duration_min']} minutes" if workout.get("duration_min") else "not specified"
    return f"""\
Workout type: {workout.get("workout_type", "Unknown")}
Intensity: {workout.get("intensity", "unknown")}
Distance: {dist}
Elevation gain: {elev}
Duration: {dur}
Notes: {workout.get("description") or "none"}

Athlete profile:
{profile_text or "No profile provided."}

Keep the JSON keys exactly as specified (hydration values stay in ml); write any amounts in \
"notes" using {describe_for_prompt(units)}."""


def parse_nutrition_response(text: str) -> dict:
    """The JSON object in a model reply, tolerating code fences or prose around it."""
    text = text.strip()
    text = re.sub(r"^```[a-z]*\n?", "", text)
    text = re.sub(r"\n?```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Smaller models sometimes wrap the object in a sentence; take the outermost braces.
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise
        return json.loads(text[start : end + 1])


def analyze_nutrition(
    workout: dict, profile_text: str, backend, units: UnitSystem = DEFAULT_UNIT_SYSTEM
) -> dict:
    """Generate nutrition recommendations for a planned workout with the selected backend."""
    prompt = _build_prompt(workout, profile_text, units)
    text = backend.stateless_turn(
        NUTRITION_SYSTEM_PROMPT, prompt, on_token=lambda _: None, source="nutrition"
    )
    return parse_nutrition_response(text)
