"""Route-fit analysis: does a RideWithGPS route suit a planned workout's goal?"""

import json
import re

ROUTE_ANALYSIS_SYSTEM_PROMPT = """\
You are an expert coach evaluating whether a specific route is appropriate for a planned workout.

Respond with ONLY a valid JSON object — no prose, no markdown fences, no explanation outside the JSON.
The object must have exactly these keys:
  "verdict"     — one of "good_match", "too_hard", "too_easy", "wrong_terrain", "needs_info"
  "explanation" — 2-4 sentences explaining the verdict, citing specific route characteristics
                  (distance, elevation gain, terrain, surface, climb profile) against the
                  workout's stated goal
  "suggestion"  — optional string: a concrete tweak if the route is a mismatch (e.g. "only ride
                  the first 20km then turn back to cut the climbing in half"), or null if the
                  route is already a good match

Use "needs_info" only if the workout has no clear goal/intensity to judge the route against.\
"""


def _strip_json_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```[a-z]*\n?", "", text)
    text = re.sub(r"\n?```$", "", text)
    return text


def _elevation_table(profile: list[dict]) -> str:
    header = "Distance (km) | Elevation (m) | Grade (%)"
    sep = "-" * len(header)
    rows = [
        f"{p['distance_km']:13.1f} | {p['elevation_m']:13.1f} | "
        f"{p['grade_pct'] if p['grade_pct'] is not None else '—'}"
        for p in profile
    ]
    return header + "\n" + sep + "\n" + "\n".join(rows)


def build_route_analysis_prompt(
    workout: dict,
    route_summary: dict,
    elevation_profile: list[dict],
    profile_text: str,
) -> str:
    dist = f"{workout['distance_km']} km" if workout.get("distance_km") else "not specified"
    dur = f"{workout['duration_min']} min" if workout.get("duration_min") else "not specified"
    sections = [
        "## Planned Workout (the goal to evaluate the route against)\n"
        f"Type: {workout.get('workout_type', 'Unknown')}\n"
        f"Intensity: {workout.get('intensity', 'unknown')}\n"
        f"Planned distance: {dist}\n"
        f"Planned duration: {dur}\n"
        f"Notes: {workout.get('description') or 'none'}",
        "## Route\n"
        f"Name: {route_summary.get('name') or 'Unnamed route'}\n"
        f"Distance: {round((route_summary.get('distance_m') or 0) / 1000, 1)} km\n"
        f"Elevation gain: {round(route_summary.get('elevation_gain_m') or 0)} m\n"
        f"Elevation loss: {round(route_summary.get('elevation_loss_m') or 0)} m\n"
        f"Terrain: {route_summary.get('terrain') or 'unknown'}\n"
        f"Difficulty (per RideWithGPS): {route_summary.get('difficulty') or 'unknown'}\n"
        f"Surface: {route_summary.get('surface') or 'unknown'} "
        f"({route_summary.get('unpaved_pct') or 0}% unpaved)",
    ]
    if elevation_profile:
        sections.append(
            "## Elevation Profile (sampled along the route)\n" + _elevation_table(elevation_profile)
        )
    if profile_text:
        sections.append(profile_text)
    return "\n\n".join(sections)


def parse_route_analysis_response(text: str) -> dict:
    parsed = json.loads(_strip_json_fences(text))
    return {
        "verdict": parsed.get("verdict", "needs_info"),
        "explanation": parsed.get("explanation", ""),
        "suggestion": parsed.get("suggestion"),
    }
