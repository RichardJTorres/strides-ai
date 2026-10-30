"""Training block generation for the Calendar page's explicit "Generate" flow."""

from .memory_context import memory_timeline_section

import json
import re
from datetime import date as date_cls

from .coach import build_training_log, units_section
from .db.models import TrainingPlan
from .modes import MODES
from .units import DEFAULT_UNIT_SYSTEM, Quantity, UnitSystem, to_si, unit_label
from .workout_structure import (
    INDOOR_RIDE_GUIDANCE,
    STRUCTURE_PROMPT,
    render_text,
    structure_for_type,
    structure_from_json,
    total_seconds,
)

# How far before/after the requested range to pull existing plan entries as
# context (ramp-up / taper continuity), without letting the model touch them.
SURROUNDING_WINDOW_DAYS = 14

_PLAN_GENERATION_SYSTEM_PROMPT_TEMPLATE = """\
You are an expert coach generating a structured training block for the athlete's calendar.

Respond with ONLY a valid JSON object — no prose, no markdown fences, no explanation outside the JSON.
The object must have exactly these keys:
  "workouts" — array of workout objects, one per day you want to schedule. Each object has:
      "date"          (string, YYYY-MM-DD, required, must fall within the requested range)
      "workout_type"  (string, required, e.g. "Easy Run", "Long Run", "Tempo Run", "Easy Ride",
                        "Long Ride", "Tempo Ride", "Indoor Ride", "Intervals", "Cross-Training",
                        "Race", "Rest")
      "description"   (string, optional — the purpose/focus of the session)
      "distance"      (number, optional, in {distance_unit})
      "elevation"     (number, optional, elevation gain in {elevation_unit})
      "duration_min"  (integer, optional)
      "intensity"     (one of "easy", "moderate", "hard", "rest", optional)
      {structure_contract}
  "summary" — a short (2-4 sentence) explanation of the block's structure and why it fits the \
athlete right now

Only include days you want to schedule something for — you do not need an entry for every date in \
the range. Do not schedule on blocked-out days or on top of races. Use the surrounding training \
context and the Training State section (current load, weekly ramp, guardrails) to keep load \
progression and taper sensible; do not propose changes outside the requested \
date range — that context is read-only.

{indoor_guidance}\
"""


def plan_generation_system_prompt(units: UnitSystem = DEFAULT_UNIT_SYSTEM) -> str:
    return _PLAN_GENERATION_SYSTEM_PROMPT_TEMPLATE.format(
        distance_unit=unit_label(Quantity.DISTANCE, units),
        elevation_unit=unit_label(Quantity.ELEVATION, units),
        structure_contract=STRUCTURE_PROMPT,
        indoor_guidance=INDOOR_RIDE_GUIDANCE,
    )


# Kept for callers that don't know the athlete's units; metric matches the stored columns.
PLAN_GENERATION_SYSTEM_PROMPT = plan_generation_system_prompt(DEFAULT_UNIT_SYSTEM)


def _strip_json_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```[a-z]*\n?", "", text)
    text = re.sub(r"\n?```$", "", text)
    return text


def _extract_json_object(text: str) -> dict:
    """Parse the first JSON object in the text, tolerating prose or fences around it."""
    cleaned = _strip_json_fences(text)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        if start == -1:
            raise
        obj, _ = json.JSONDecoder().raw_decode(cleaned[start:])
        if not isinstance(obj, dict):
            raise TypeError("expected a JSON object")
        return obj


def _current_date_section() -> str:
    today = date_cls.today()
    return (
        f"## Current Date\n"
        f"Today is {today.strftime('%A, %B %-d, %Y')} ({today.isoformat()}). "
        "Use this to compute how long ago each entry in the Recent Activities log occurred and "
        "how far away the requested block is — do not assume any listed activity happened "
        "recently, or refer to it by day-of-week, without checking its date against today's date."
    )


def _plan_table(rows: list[dict], units: UnitSystem = DEFAULT_UNIT_SYSTEM) -> str:
    header = "Date       | Type             | Distance | Elevation | Duration | Intensity"
    sep = "-" * 76
    lines = []
    for w in rows:
        m = TrainingPlan.measure_field(w, "distance_km", units) if w.get("distance_km") else None
        dist = m.formatted if m else "—"
        e = TrainingPlan.measure_field(w, "elevation_m", units) if w.get("elevation_m") else None
        elev = e.formatted if e else "—"
        dur = f"{w['duration_min']} min" if w.get("duration_min") else "—"
        line = (
            f"{w['date']:10s} | {(w['workout_type'] or '')[:16]:16s} | "
            f"{dist:8s} | {elev:9s} | {dur:8s} | {w.get('intensity') or '—'}"
        )
        structure = structure_from_json(w.get("structure_json"))
        if structure:
            line += f"\n{'':10s}   structure: {render_text(structure)}"
        lines.append(line)
    return header + "\n" + sep + "\n" + "\n".join(lines)


def build_plan_generation_prompt(
    mode: str,
    profile_text: str,
    memories: list[dict],
    prefs: dict,
    surrounding_plan: list[dict],
    recent_activities: list[dict],
    start_date: str,
    end_date: str,
    freeform_text: str,
    units: UnitSystem = DEFAULT_UNIT_SYSTEM,
    training_state_text: str = "",
) -> str:
    cfg = MODES.get(mode, MODES["running"])
    sections = [
        cfg.system_prompt,
        units_section(units),
        _current_date_section(),
        f"## Requested Block\nGenerate a training block for {start_date} through "
        f"{end_date} (inclusive).",
    ]

    if freeform_text.strip():
        sections.append(f"## Athlete's Request\n{freeform_text.strip()}")

    if profile_text:
        sections.append(profile_text)

    context = memory_timeline_section(
        memories, date_cls.fromisoformat(start_date), date_cls.fromisoformat(end_date)
    )
    if context:
        sections.append(context)

    races = sorted(prefs.get("races", []), key=lambda r: r["date"])
    blocked = sorted(prefs.get("blocked_days", []))
    if races or blocked:
        lines = []
        if races:
            lines.append("Races:")
            lines.extend(f"  - {r['date']}: {r.get('name', 'Race')}" for r in races)
        if blocked:
            lines.append("Blocked-out days (do not schedule on these):")
            lines.extend(f"  - {d}" for d in blocked)
        sections.append("## Calendar Constraints\n" + "\n".join(lines))

    if surrounding_plan:
        sections.append(
            "## Surrounding Training Blocks (context only — do not modify these dates)\n"
            "These are currently *planned* workouts, not confirmed completed activities — "
            "check each date against today's date (see Current Date above). An entry dated "
            "before today may or may not have actually happened as planned; an entry dated "
            "today or later has definitely not happened yet. Never describe a planned entry "
            'in the past tense (e.g. not "Sunday\'s ride") unless it is confirmed by the '
            "Recent Activities log below.\n" + _plan_table(surrounding_plan, units)
        )

    if training_state_text:
        sections.append(training_state_text)

    if recent_activities:
        log = build_training_log(recent_activities, mode, units)
        sections.append(f"## Recent Activities (last {len(recent_activities)})\n\n```\n{log}\n```")

    return "\n\n".join(sections)


def _normalize_workout_units(w: dict, units: UnitSystem) -> dict:
    """The model writes distance/elevation in the athlete's units; storage is km and m.
    Entries that already use the stored keys (distance_km/elevation_m) pass through."""
    w = dict(w)
    if "distance" in w:
        meters = to_si(_as_float(w.pop("distance")), Quantity.DISTANCE, units)
        w.setdefault("distance_km", None if meters is None else round(meters / 1000, 2))
    if "elevation" in w:
        meters = to_si(_as_float(w.pop("elevation")), Quantity.ELEVATION, units)
        w.setdefault("elevation_m", None if meters is None else round(meters))
    return w


def _as_float(value) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _with_structure(w: dict) -> dict:
    """Validate the model's structure; a valid one is authoritative for duration_min."""
    structure = structure_for_type(w.get("workout_type"), w.get("structure"))
    w["structure"] = structure
    if structure:
        w["duration_min"] = round(total_seconds(structure) / 60)
    return w


def parse_plan_generation_response(
    text: str, start_date: str, end_date: str, units: UnitSystem = DEFAULT_UNIT_SYSTEM
) -> dict:
    """Parse the LLM's JSON response, dropping malformed or out-of-range entries."""
    parsed = _extract_json_object(text)
    raw_workouts = parsed.get("workouts", [])
    workouts = [
        _with_structure(_normalize_workout_units(w, units))
        for w in raw_workouts
        if w.get("date") and w.get("workout_type") and start_date <= w["date"] <= end_date
    ]
    return {"workouts": workouts, "summary": parsed.get("summary", "")}
