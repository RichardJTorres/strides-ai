"""Training block generation for the Calendar page's explicit "Generate" flow."""

import json
import re
from datetime import date as date_cls

from .coach import build_training_log
from .modes import MODES

# How far before/after the requested range to pull existing plan entries as
# context (ramp-up / taper continuity), without letting the model touch them.
SURROUNDING_WINDOW_DAYS = 14

PLAN_GENERATION_SYSTEM_PROMPT = """\
You are an expert coach generating a structured training block for the athlete's calendar.

Respond with ONLY a valid JSON object — no prose, no markdown fences, no explanation outside the JSON.
The object must have exactly these keys:
  "workouts" — array of workout objects, one per day you want to schedule. Each object has:
      "date"          (string, YYYY-MM-DD, required, must fall within the requested range)
      "workout_type"  (string, required, e.g. "Easy Run", "Long Run", "Tempo Run", "Easy Ride",
                        "Long Ride", "Tempo Ride", "Indoor Ride", "Intervals", "Cross-Training",
                        "Race", "Rest")
      "description"   (string, optional — the purpose/focus of the session)
      "distance_km"   (number, optional)
      "elevation_m"   (number, optional)
      "duration_min"  (integer, optional)
      "intensity"     (one of "easy", "moderate", "hard", "rest", optional)
  "summary" — a short (2-4 sentence) explanation of the block's structure and why it fits the \
athlete right now

Only include days you want to schedule something for — you do not need an entry for every date in \
the range. Do not schedule on blocked-out days or on top of races. Use the surrounding training \
context to keep load progression and taper sensible; do not propose changes outside the requested \
date range — that context is read-only.\
"""


def _strip_json_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```[a-z]*\n?", "", text)
    text = re.sub(r"\n?```$", "", text)
    return text


def _current_date_section() -> str:
    today = date_cls.today()
    return (
        f"## Current Date\n"
        f"Today is {today.strftime('%A, %B %-d, %Y')} ({today.isoformat()}). "
        "Use this to compute how long ago each entry in the Recent Activities log occurred and "
        "how far away the requested block is — do not assume any listed activity happened "
        "recently, or refer to it by day-of-week, without checking its date against today's date."
    )


def _plan_table(rows: list[dict]) -> str:
    header = "Date       | Type             | Distance | Duration | Intensity"
    sep = "-" * 65
    lines = []
    for w in rows:
        dist = f"{w['distance_km']} km" if w.get("distance_km") else "—"
        dur = f"{w['duration_min']} min" if w.get("duration_min") else "—"
        lines.append(
            f"{w['date']:10s} | {(w['workout_type'] or '')[:16]:16s} | "
            f"{dist:8s} | {dur:8s} | {w.get('intensity') or '—'}"
        )
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
) -> str:
    cfg = MODES.get(mode, MODES["running"])
    sections = [
        cfg.system_prompt,
        _current_date_section(),
        f"## Requested Block\nGenerate a training block for {start_date} through "
        f"{end_date} (inclusive).",
    ]

    if freeform_text.strip():
        sections.append(f"## Athlete's Request\n{freeform_text.strip()}")

    if profile_text:
        sections.append(profile_text)

    if memories:
        lines = "\n".join(f"  [{m['category']}] {m['content']}" for m in memories)
        sections.append(f"## Coaching Notes (goals, races, injuries, preferences)\n{lines}")

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
            "Recent Activities log below.\n" + _plan_table(surrounding_plan)
        )

    if recent_activities:
        log = build_training_log(recent_activities, mode)
        sections.append(f"## Recent Activities (last {len(recent_activities)})\n\n```\n{log}\n```")

    return "\n\n".join(sections)


def parse_plan_generation_response(text: str, start_date: str, end_date: str) -> dict:
    """Parse the LLM's JSON response, dropping malformed or out-of-range entries."""
    parsed = json.loads(_strip_json_fences(text))
    raw_workouts = parsed.get("workouts", [])
    workouts = [
        w
        for w in raw_workouts
        if w.get("date") and w.get("workout_type") and start_date <= w["date"] <= end_date
    ]
    return {"workouts": workouts, "summary": parsed.get("summary", "")}
