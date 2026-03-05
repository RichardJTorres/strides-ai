"""AI-powered training schedule generation and revision."""

import json
import os
import re
from datetime import date, timedelta

import anthropic

MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")

DAYS_OF_WEEK = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]

SYSTEM_PROMPT = """\
You are an expert running coach generating a structured training schedule.
You must respond with ONLY a valid JSON array — no prose, no markdown fences, no explanation.
Each element represents one training day and must have these keys:
  "date"         – YYYY-MM-DD string
  "workout_type" – one of: "Easy Run", "Tempo Run", "Long Run", "Interval", "Race", "Rest", "Cross-Training"
  "description"  – 1-3 sentence description of the workout
  "distance_km"  – number or null (null for Rest)
  "duration_min" – number or null (null for Rest)
  "intensity"    – one of: "easy", "moderate", "hard", "rest"

Include EVERY day in the date range (including rest days). Do not skip any dates.
"""


def _format_activities(activities: list[dict]) -> str:
    if not activities:
        return "No recent activity data available."
    lines = ["DATE       | TYPE        | DIST(km) | PACE(/km) | AVG HR"]
    lines.append("-" * 58)
    for a in activities:
        dist_km = round((a.get("distance_m") or 0) / 1000, 1)
        pace_s = a.get("avg_pace_s_per_km")
        if pace_s:
            pace = f"{int(pace_s // 60)}:{int(pace_s % 60):02d}"
        else:
            pace = "—"
        hr = int(a.get("avg_hr") or 0) or "—"
        lines.append(f"{a.get('date','')} | {a.get('sport_type','Run'):<11} | {dist_km:<8} | {pace:<9} | {hr}")
    return "\n".join(lines)


def _date_range(start: date, end: date) -> list[str]:
    days = []
    cur = start
    while cur <= end:
        days.append(cur.isoformat())
        cur += timedelta(days=1)
    return days


def _build_prompt(prefs: dict, profile_text: str, recent_activities: list[dict]) -> str:
    today = date.today()

    # Determine end date: nearest future race or 12 weeks out
    end_date = today + timedelta(weeks=12)
    races = prefs.get("races") or []
    future_races = sorted(
        [r for r in races if r.get("date", "") >= today.isoformat()],
        key=lambda r: r["date"],
    )
    if future_races:
        end_date = date.fromisoformat(future_races[0]["date"])

    date_range = _date_range(today, end_date)

    race_lines = "\n".join(
        f"  - {r['date']}: {r['name']}" + (f" (target: {r['target_time']})" if r.get("target_time") else "")
        for r in future_races
    ) or "  None"

    blocked = prefs.get("blocked_days") or []
    blocked_str = ", ".join(blocked) if blocked else "None"

    rest_days = prefs.get("rest_days") or []
    long_run_days = prefs.get("long_run_days") or []
    frequency = prefs.get("frequency", 4)

    long_run_constraint = (
        f"HARD RULE — Long Run placement: EVERY week's Long Run MUST fall on one of these days: "
        f"{', '.join(long_run_days)}. Do NOT assign workout_type 'Long Run' to any other day of the week."
        if long_run_days else
        "Long Run placement: no day preference set — distribute Long Runs sensibly."
    )

    rest_constraint = (
        f"HARD RULE — Rest days: NEVER assign a run or cross-training workout on these days of the week: "
        f"{', '.join(rest_days)}. These days must always have workout_type 'Rest'."
        if rest_days else
        "Rest days: no fixed rest days set."
    )

    blocked_constraint = (
        f"HARD RULE — Blocked dates: these specific calendar dates must have workout_type 'Rest': {blocked_str}."
        if blocked else
        "Blocked dates: none."
    )

    return f"""\
Athlete profile:
{profile_text or "No profile provided."}

Recent training (last 8 weeks):
{_format_activities(recent_activities)}

Schedule constraints:
- Date range: {today.isoformat()} to {end_date.isoformat()} ({len(date_range)} days total)
- Training frequency: {frequency} runs per week
- {rest_constraint}
- {long_run_constraint}
- {blocked_constraint}
- Upcoming races:
{race_lines}

Generate a complete training schedule covering every day from {today.isoformat()} to {end_date.isoformat()}.
Honor the target race date(s) by tapering appropriately in the final 1-2 weeks.
Return ONLY the JSON array."""


def _parse_response(text: str) -> list[dict]:
    text = text.strip()
    # Strip markdown fences if the model adds them anyway
    text = re.sub(r"^```[a-z]*\n?", "", text)
    text = re.sub(r"\n?```$", "", text)
    workouts = json.loads(text)
    cleaned = []
    for w in workouts:
        cleaned.append({
            "date": w["date"],
            "workout_type": w.get("workout_type", "Rest"),
            "description": w.get("description", ""),
            "distance_km": w.get("distance_km"),
            "duration_min": w.get("duration_min"),
            "intensity": w.get("intensity", "rest"),
        })
    return cleaned


def _enforce_constraints(workouts: list[dict], prefs: dict) -> list[dict]:
    """Hard-enforce rest days, blocked days, and long run day placement."""
    rest_days = set(prefs.get("rest_days") or [])
    long_run_days = set(prefs.get("long_run_days") or [])
    blocked_days = set(prefs.get("blocked_days") or [])

    for w in workouts:
        dow = DAYS_OF_WEEK[date.fromisoformat(w["date"]).weekday() % 7]
        # weekday() returns 0=Mon…6=Sun; map to our Sunday-first list
        dow = DAYS_OF_WEEK[date.fromisoformat(w["date"]).isoweekday() % 7]

        # Blocked dates → always Rest
        if w["date"] in blocked_days:
            w["workout_type"] = "Rest"
            w["intensity"] = "rest"
            w["distance_km"] = None
            w["duration_min"] = None

        # Rest day preference → always Rest (unless it's a race day)
        elif dow in rest_days and w["workout_type"] != "Race":
            w["workout_type"] = "Rest"
            w["intensity"] = "rest"
            w["distance_km"] = None
            w["duration_min"] = None

        # Long Run placed on a non-preferred day → demote to Easy Run
        elif long_run_days and w["workout_type"] == "Long Run" and dow not in long_run_days:
            w["workout_type"] = "Easy Run"
            w["intensity"] = "easy"

    return workouts


def generate_schedule(prefs: dict, profile_text: str, recent_activities: list[dict], api_key: str) -> list[dict]:
    """Generate a full training schedule from scratch."""
    client = anthropic.Anthropic(api_key=api_key)
    prompt = _build_prompt(prefs, profile_text, recent_activities)
    response = client.messages.create(
        model=MODEL,
        max_tokens=8096,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    workouts = _parse_response(response.content[0].text)
    return _enforce_constraints(workouts, prefs)


def revise_schedule(
    current_plan: list[dict],
    feedback: str,
    prefs: dict,
    profile_text: str,
    api_key: str,
) -> list[dict]:
    """Revise an existing schedule based on athlete feedback."""
    client = anthropic.Anthropic(api_key=api_key)
    plan_json = json.dumps(current_plan, indent=2)
    prompt = f"""\
Here is the athlete's current training schedule:

{plan_json}

The athlete has this feedback:
"{feedback}"

Please revise the schedule to address this feedback.
Keep all constraints from the original schedule (rest days, blocked days, race dates, frequency).
Return the COMPLETE revised schedule as a JSON array covering the same date range.
Return ONLY the JSON array."""

    response = client.messages.create(
        model=MODEL,
        max_tokens=8096,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    workouts = _parse_response(response.content[0].text)
    return _enforce_constraints(workouts, prefs)
