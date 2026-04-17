"""Coaching system prompt assembly and history utilities."""

import sqlite3
from datetime import datetime

from .db import RUN_TYPES
from . import db

RECALL_MESSAGES = 40
# Number of most-recent activities always pinned in the system prompt each turn.
# The full training log is seeded once in conversation history via build_initial_history.
RECENT_ACTIVITIES_IN_SYSTEM = 30

RUNNING_SYSTEM_PROMPT = """\
You are an experienced, data-driven running coach with access to the athlete's \
complete Strava training log. Your role is to:

- Analyse training load, trends, and patterns from the data provided.
- Answer questions about specific workouts, weekly/monthly volume, and progress.
- Give evidence-based coaching advice: pacing, recovery, race preparation, \
injury prevention, and periodisation.
- Be concise but thorough. When referencing specific runs, cite the date and \
key metrics (distance, pace, HR).
- Use metric units (km, min/km) unless the athlete asks otherwise.
- When advising on nutrition for a run, suggest a concrete sample loadout \
(e.g. "2 gels, 1 granola bar, 500 ml electrolytes"). If the athlete has listed \
preferred snacks in their profile, choose from those; otherwise use sensible \
defaults based on run distance and intensity.

The athlete's complete training log is included below. Treat it as ground \
truth for all data-related questions.

**Memory:** Use the save_memory tool proactively whenever the athlete mentions \
goals, upcoming races, injuries, preferences, or any key context that should \
persist across sessions.\
"""

CYCLING_SYSTEM_PROMPT = """\
You are an experienced, data-driven cycling coach with access to the athlete's \
complete Strava training log. Your role is to:

- Analyse training load, trends, and patterns from cycling data provided.
- Answer questions about specific rides, weekly/monthly volume, and progress.
- Give evidence-based coaching advice: pacing, power, recovery, race preparation, \
injury prevention, and periodisation for cyclists.
- Be concise but thorough. When referencing specific rides, cite the date and \
key metrics (distance, speed, HR).
- Use metric units (km, km/h) unless the athlete asks otherwise.
- When advising on nutrition for a ride, suggest a concrete sample loadout \
(e.g. "2 gels, 1 energy bar, 750 ml electrolytes"). If the athlete has listed \
preferred snacks in their profile, choose from those; otherwise use sensible \
defaults based on ride duration and intensity.

The athlete's complete training log is included below. Treat it as ground \
truth for all data-related questions.

**Memory:** Use the save_memory tool proactively whenever the athlete mentions \
goals, upcoming events, injuries, preferences, or any key context that should \
persist across sessions.\
"""

HYBRID_SYSTEM_PROMPT = """\
You are an experienced, data-driven multisport coach with access to the athlete's \
complete Strava training log covering both running and cycling. Your role is to:

- Analyse training load, trends, and patterns across all sport types.
- Answer questions about specific workouts, weekly/monthly volume, and progress.
- Give evidence-based coaching advice covering both running and cycling: \
pacing, recovery, race preparation, injury prevention, and periodisation.
- Be concise but thorough. When referencing specific activities, cite the date, \
sport type, and key metrics.
- Use metric units unless the athlete asks otherwise.
- When advising on nutrition for any activity, suggest a concrete sample loadout \
(e.g. "2 gels, 1 granola bar, 500 ml electrolytes"). If the athlete has listed \
preferred snacks in their profile, choose from those; otherwise use sensible \
defaults based on activity duration and intensity.

The athlete's complete training log is included below. Treat it as ground \
truth for all data-related questions.

**Memory:** Use the save_memory tool proactively whenever the athlete mentions \
goals, upcoming events, injuries, preferences, or any key context that should \
persist across sessions.\
"""

_PROMPT_BY_MODE = {
    "running": RUNNING_SYSTEM_PROMPT,
    "cycling": CYCLING_SYSTEM_PROMPT,
    "hybrid": HYBRID_SYSTEM_PROMPT,
}


def build_system(
    profile: str,
    memories: list[dict],
    mode: str = "running",
    activities: list | None = None,
) -> str:
    prompt = _PROMPT_BY_MODE.get(mode, RUNNING_SYSTEM_PROMPT)

    now = datetime.now().astimezone()
    day_str = now.strftime("%A, %B %-d, %Y")
    time_str = now.strftime("%-I:%M %p %Z")
    prompt += (
        f"\n\n## Current Date & Time\n"
        f"Today is {day_str} at {time_str}. "
        "Use this to reason about training timing, upcoming workouts, recovery windows, "
        "and time elapsed since past activities. "
        "Do not mention the date or time in responses unless directly relevant to the athlete's question."
    )

    if profile:
        prompt += f"\n\n{profile}"

    if memories:
        lines = [f"  [{m['category']}] {m['content']}" for m in memories]
        prompt += "\n\n## Coaching Notes (remembered from previous sessions)\n" + "\n".join(lines)

    upcoming = db.get_upcoming_planned_workouts()
    if upcoming:
        header = "Date       | Type             | Distance | Duration | Intensity"
        sep = "-" * 65
        rows = []
        for w in upcoming:
            dist = f"{w['distance_km']} km" if w.get("distance_km") else "—"
            dur = f"{w['duration_min']} min" if w.get("duration_min") else "—"
            rows.append(
                f"{w['date']:10s} | {(w['workout_type'] or '')[:16]:16s} | {dist:8s} | {dur:8s} | {w.get('intensity') or '—'}"
            )
        prompt += (
            "\n\n## Upcoming Planned Workouts (next 14 days)\n"
            + header
            + "\n"
            + sep
            + "\n"
            + "\n".join(rows)
        )

    # Pin only the most recent activities every turn (cheap, always survives truncation).
    # The full training log is seeded once in conversation history.
    recent = (activities or [])[:RECENT_ACTIVITIES_IN_SYSTEM]

    # Inject metrics guide when any activity has been analyzed
    has_analysis = any(a.get("analysis_summary") for a in recent)
    if has_analysis:
        prompt += (
            "\n\n## Analysis Metrics Guide\n"
            "The ANALYSIS column in the training log contains auto-generated summaries. "
            "Key metrics to reason about:\n"
            "- **Cardiac decoupling %**: aerobic efficiency; <5% = well-coupled (good), "
            "5–10% = moderate stress, >10% = high cardiovascular drift\n"
            "- **Effort efficiency score**: 0–100, normalized vs athlete's full history; "
            "higher = more efficient pace for a given HR\n"
            "- **HR zones**: Z1=recovery, Z2=aerobic base, Z3=tempo, "
            "Z4=threshold, Z5=VO2max/max effort\n"
            "- **Pace fade**: sec/mile change in final third vs first third; "
            "positive = slowing (possible fatigue), negative = negative split"
        )

    recent_log = build_training_log(recent, mode)
    prompt += (
        f"\n\n## Recent Activities (last {RECENT_ACTIVITIES_IN_SYSTEM})\n\n```\n{recent_log}\n```"
    )

    return prompt


def _format_pace(s_per_km: float | None) -> str:
    if s_per_km is None:
        return "—"
    mins = int(s_per_km // 60)
    secs = int(s_per_km % 60)
    return f"{mins}:{secs:02d}/km"


def _format_speed(s_per_km: float | None) -> str:
    if s_per_km is None or s_per_km <= 0:
        return "—"
    kph = 3600 / s_per_km
    return f"{kph:.1f}km/h"


def _format_duration(seconds: int | None) -> str:
    if seconds is None:
        return "—"
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h{m:02d}m{s:02d}s"
    return f"{m}m{s:02d}s"


def build_training_log(rows: list[sqlite3.Row], mode: str = "running") -> str:
    if not rows:
        return "No activities found."

    if mode == "hybrid":
        header = "DATE       | TYPE       | NAME                           | DIST(km) | DURATION | PACE/SPEED  | AVG HR | MAX HR | CADENCE | ELEV(m) | SUFFER | RPE | ANALYSIS"
        sep = "-" * 215
    elif mode == "cycling":
        header = "DATE       | NAME                           | DIST(km) | DURATION | SPEED    | AVG HR | MAX HR | CADENCE(rpm) | ELEV(m) | SUFFER | RPE | ANALYSIS"
        sep = "-" * 200
    else:
        header = "DATE       | NAME                           | DIST(km) | DURATION | PACE     | AVG HR | MAX HR | CADENCE(spm) | ELEV(m) | SUFFER | RPE | ANALYSIS"
        sep = "-" * 200

    lines = [header, sep]

    for r in reversed(rows):
        dist_km = (r["distance_m"] or 0) / 1000
        sport = r["sport_type"] or ""
        is_run = sport in RUN_TYPES

        analysis = (r.get("analysis_summary") or "")[:60]

        if mode == "hybrid":
            pace_speed = (
                _format_pace(r["avg_pace_s_per_km"])
                if is_run
                else _format_speed(r["avg_pace_s_per_km"])
            )
            lines.append(
                f"{r['date'] or '?':10s} | "
                f"{sport[:10]:10s} | "
                f"{(r['name'] or '')[:30]:30s} | "
                f"{dist_km:8.2f} | "
                f"{_format_duration(r['moving_time_s']):8s} | "
                f"{pace_speed:11s} | "
                f"{r['avg_hr'] or '—':6} | "
                f"{r['max_hr'] or '—':6} | "
                f"{r['avg_cadence'] or '—':7} | "
                f"{r['elevation_gain_m'] or '—':7} | "
                f"{r['suffer_score'] or '—':6} | "
                f"{r['perceived_exertion'] or '—':3} | "
                f"{analysis}"
            )
        elif mode == "cycling":
            lines.append(
                f"{r['date'] or '?':10s} | "
                f"{(r['name'] or '')[:30]:30s} | "
                f"{dist_km:8.2f} | "
                f"{_format_duration(r['moving_time_s']):8s} | "
                f"{_format_speed(r['avg_pace_s_per_km']):8s} | "
                f"{r['avg_hr'] or '—':6} | "
                f"{r['max_hr'] or '—':6} | "
                f"{r['avg_cadence'] or '—':12} | "
                f"{r['elevation_gain_m'] or '—':7} | "
                f"{r['suffer_score'] or '—':6} | "
                f"{r['perceived_exertion'] or '—':3} | "
                f"{analysis}"
            )
        else:  # running
            lines.append(
                f"{r['date'] or '?':10s} | "
                f"{(r['name'] or '')[:30]:30s} | "
                f"{dist_km:8.2f} | "
                f"{_format_duration(r['moving_time_s']):8s} | "
                f"{_format_pace(r['avg_pace_s_per_km']):8s} | "
                f"{r['avg_hr'] or '—':6} | "
                f"{r['max_hr'] or '—':6} | "
                f"{r['avg_cadence'] or '—':12} | "
                f"{r['elevation_gain_m'] or '—':7} | "
                f"{r['suffer_score'] or '—':6} | "
                f"{r['perceived_exertion'] or '—':3} | "
                f"{analysis}"
            )

    total_km = sum((r["distance_m"] or 0) / 1000 for r in rows)
    act_label = "runs" if mode == "running" else "rides" if mode == "cycling" else "activities"
    lines.append(sep)
    lines.append(f"Total: {len(rows)} {act_label}, {total_km:.1f} km")
    return "\n".join(lines)


def build_initial_history(
    activities: list, prior_messages: list[dict], mode: str = "running"
) -> list[dict]:
    """
    Seed the backend's conversation history with the full training log (once)
    followed by any recalled prior messages.

    The system prompt carries only the most recent RECENT_ACTIVITIES_IN_SYSTEM
    activities on every turn, so this full-log seed is the only place older
    history lives. It may be gracefully truncated by small-context models, but
    only the oldest runs are dropped — recent ones are protected by the system prompt.
    """
    training_log = build_training_log(activities, mode)
    act_label = "runs" if mode == "running" else "rides" if mode == "cycling" else "activities"
    log_message = f"Here is the athlete's complete training log:\n\n```\n{training_log}\n```"
    return [
        {"role": "user", "content": log_message},
        {
            "role": "assistant",
            "content": (
                f"Got it — I have your full training log loaded ({len(activities)} {act_label}). "
                "What would you like to discuss?"
            ),
        },
        *[{"role": m["role"], "content": m["content"]} for m in prior_messages],
    ]
