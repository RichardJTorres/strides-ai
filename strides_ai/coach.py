"""Coaching system prompt assembly and history utilities."""

import sqlite3
from datetime import datetime

from . import db
from .modes import MODES

RECALL_MESSAGES = 40
# Number of most-recent activities always pinned in the system prompt each turn.
# The full training log is seeded once in conversation history via build_initial_history.
RECENT_ACTIVITIES_IN_SYSTEM = 30
# How far ahead planned workouts are surfaced, wide enough to cover a multi-week
# training block the coach is asked to generate or regenerate.
PLANNED_WORKOUTS_WINDOW_DAYS = 60

VOICE_INSTRUCTIONS: dict[str, str] = {
    "supportive": (
        "## Coaching Voice\n"
        "Communicate with warmth and encouragement. Celebrate every win, no matter how small. "
        "Emphasise progress over performance. Frame setbacks constructively and use inclusive, "
        "affirming language throughout."
    ),
    "motivational": (
        "## Coaching Voice\n"
        "Be high-energy and inspirational. Push the athlete toward their goals with genuine excitement. "
        "Use strong, vivid language. Remind them why they started and what they're capable of. "
        "Keep the energy up throughout every response."
    ),
    "technical": (
        "## Coaching Voice\n"
        "Be analytical and data-driven. Lean into metrics, zones, ratios, and trends. "
        "Minimise small talk — get to the numbers quickly. Use precise terminology "
        "(e.g. lactate threshold, progressive overload, HR zone distribution). "
        "Support every recommendation with data from the training log."
    ),
    "aggressive": (
        "## Coaching Voice\n"
        "Be direct and demanding. No sugarcoating — if the data shows underperformance, say so. "
        "Push harder. Keep responses concise and action-oriented. "
        "Focus on results, not feelings."
    ),
    "beginner_friendly": (
        "## Coaching Voice\n"
        "Be patient and educational. Avoid jargon — explain any technical terms you use. "
        "Break advice into simple, concrete steps. Reassure the athlete that progress takes time "
        "and that consistency matters more than perfection. Prioritise clarity over brevity."
    ),
    "conversational": (
        "## Coaching Voice\n"
        "Be casual and relaxed, like talking to a training buddy. Keep formality low. "
        "Use natural, colloquial language and feel free to be a bit chatty. "
        "Make the athlete feel like they're having a conversation, not receiving a lecture."
    ),
}


# ── build_system section helpers ──────────────────────────────────────────────


def _voice_section(coach_voice: str) -> str:
    block = VOICE_INSTRUCTIONS.get(coach_voice, "")
    if not block and coach_voice:
        block = f"## Coaching Voice\n{coach_voice}"
    return block


def _datetime_section() -> str:
    now = datetime.now().astimezone()
    day_str = now.strftime("%A, %B %-d, %Y")
    time_str = now.strftime("%-I:%M %p %Z")
    return (
        f"## Current Date & Time\n"
        f"Today is {day_str} at {time_str}. "
        "Use this to reason about training timing, upcoming workouts, recovery windows, "
        "and time elapsed since past activities. "
        "Do not mention the date or time in responses unless directly relevant to the athlete's question."
    )


def _memories_section(memories: list[dict]) -> str:
    if not memories:
        return ""
    lines = [f"  [{m['category']}] {m['content']}" for m in memories]
    return "## Coaching Notes (remembered from previous sessions)\n" + "\n".join(lines)


def _upcoming_workouts_section() -> str:
    upcoming = db.get_upcoming_planned_workouts(days=PLANNED_WORKOUTS_WINDOW_DAYS)
    if not upcoming:
        return ""
    header = "Date       | Type             | Distance | Duration | Intensity"
    sep = "-" * 65
    rows = []
    for w in upcoming:
        dist = f"{w['distance_km']} km" if w.get("distance_km") else "—"
        dur = f"{w['duration_min']} min" if w.get("duration_min") else "—"
        rows.append(
            f"{w['date']:10s} | {(w['workout_type'] or '')[:16]:16s} | {dist:8s} | {dur:8s} | {w.get('intensity') or '—'}"
        )
    return (
        f"## Upcoming Planned Workouts (next {PLANNED_WORKOUTS_WINDOW_DAYS} days)\n"
        + header
        + "\n"
        + sep
        + "\n"
        + "\n".join(rows)
    )


def _calendar_prefs_section() -> str:
    prefs = db.get_calendar_prefs()
    today = datetime.now().date().isoformat()
    races = sorted(
        (r for r in prefs.get("races", []) if r.get("date", "") >= today), key=lambda r: r["date"]
    )
    blocked = sorted(d for d in prefs.get("blocked_days", []) if d >= today)
    if not races and not blocked:
        return ""
    lines = []
    if races:
        lines.append("Upcoming races:")
        lines.extend(f"  - {r['date']}: {r.get('name', 'Race')}" for r in races)
    if blocked:
        lines.append("Blocked-out days (do not schedule workouts on these dates):")
        lines.extend(f"  - {d}" for d in blocked)
    return "## Calendar Constraints\n" + "\n".join(lines)


def _analysis_guide_section(cfg, recent: list) -> str:
    if not cfg.has_analysis or not any(a.get("analysis_summary") for a in recent):
        return ""
    return (
        "## Analysis Metrics Guide\n"
        "The ANALYSIS column in the training log contains auto-generated summaries. "
        "Treat all metrics as equally important inputs — no single metric defines a run.\n"
        "- **HR zones**: Z1=recovery, Z2=aerobic base, Z3=tempo, Z4=threshold, Z5=VO2max; "
        "Z1/Z2 time builds aerobic base, high Z4/Z5 indicates intensity work\n"
        "- **Effort efficiency score**: 0–100, normalized vs athlete's full history; "
        "higher = more efficient pace for a given HR; tracks fitness trends over time\n"
        "- **Pace fade**: sec/mile change in final third vs first third; "
        "positive = slowing (fatigue or poor pacing), negative = negative split (strong finish)\n"
        "- **Cardiac decoupling %**: HR drift relative to pace; <5% = well-coupled, "
        "5–10% = moderate drift, >10% = high drift; most meaningful for steady aerobic runs"
    )


def _recent_activities_section(recent: list, mode: str) -> str:
    log = build_training_log(recent, mode)
    return f"## Recent Activities (last {RECENT_ACTIVITIES_IN_SYSTEM})\n\n```\n{log}\n```"


# ── Public API ────────────────────────────────────────────────────────────────


def build_system(
    profile: str,
    memories: list[dict],
    mode: str = "running",
    activities: list | None = None,
    coach_voice: str = "",
) -> str:
    cfg = MODES.get(mode, MODES["running"])
    # Pin only the most recent activities every turn (cheap, always survives truncation).
    # The full training log is seeded once in conversation history via build_initial_history.
    recent = (activities or [])[:RECENT_ACTIVITIES_IN_SYSTEM]

    sections = [
        cfg.system_prompt,
        _voice_section(coach_voice),
        _datetime_section(),
        profile,  # already carries its own ## header from profile.py; empty string is filtered out
        _memories_section(memories),
        _calendar_prefs_section(),
        _upcoming_workouts_section(),
        _analysis_guide_section(cfg, recent),
        _recent_activities_section(recent, mode),
    ]
    return "\n\n".join(s for s in sections if s)


def build_training_log(rows: list[sqlite3.Row], mode: str = "running") -> str:
    if not rows:
        return "No activities found."
    cfg = MODES.get(mode, MODES["running"])

    # When activities span multiple sport types, use the hybrid formatter
    # (it has a TYPE column and handles mixed pace/speed/duration display).
    if cfg.sport_types is not None:  # hybrid already uses its own formatter
        types_present = {(r.get("sport_type") or "") for r in rows}
        if not types_present.issubset(cfg.sport_types):
            cfg = MODES["hybrid"]

    sep = "-" * cfg.log_sep_len
    lines = [cfg.log_header, sep]
    for r in reversed(rows):
        lines.append(cfg.format_log_row(r))
    lines.append(sep)
    lines.append(cfg.format_log_total(rows))
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
    log_message = f"Here is the athlete's complete training log:\n\n```\n{training_log}\n```"
    return [
        {"role": "user", "content": log_message},
        {
            "role": "assistant",
            "content": (
                f"Got it — I have your full training log loaded ({len(activities)} activities). "
                "What would you like to discuss?"
            ),
        },
        *[{"role": m["role"], "content": m["content"]} for m in prior_messages],
    ]
