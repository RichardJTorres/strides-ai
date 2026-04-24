"""Coaching system prompt assembly and history utilities."""

import sqlite3
from datetime import datetime

from . import db
from .modes import MODES

RECALL_MESSAGES = 40
# Number of most-recent activities always pinned in the system prompt each turn.
# The full training log is seeded once in conversation history via build_initial_history.
RECENT_ACTIVITIES_IN_SYSTEM = 30

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
        "(e.g. cardiac decoupling, lactate threshold, progressive overload). "
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


def build_system(
    profile: str,
    memories: list[dict],
    mode: str = "running",
    activities: list | None = None,
    coach_voice: str = "",
) -> str:
    cfg = MODES.get(mode, MODES["running"])
    prompt = cfg.system_prompt

    voice_block = VOICE_INSTRUCTIONS.get(coach_voice, "")
    if not voice_block and coach_voice:
        voice_block = f"## Coaching Voice\n{coach_voice}"
    if voice_block:
        prompt += f"\n\n{voice_block}"

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

    if cfg.has_analysis and any(a.get("analysis_summary") for a in recent):
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


def build_training_log(rows: list[sqlite3.Row], mode: str = "running") -> str:
    if not rows:
        return "No activities found."
    cfg = MODES.get(mode, MODES["running"])
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
    cfg = MODES.get(mode, MODES["running"])
    training_log = build_training_log(activities, mode)
    log_message = f"Here is the athlete's complete training log:\n\n```\n{training_log}\n```"
    return [
        {"role": "user", "content": log_message},
        {
            "role": "assistant",
            "content": (
                f"Got it — I have your full training log loaded ({len(activities)} {cfg.activity_label}). "
                "What would you like to discuss?"
            ),
        },
        *[{"role": m["role"], "content": m["content"]} for m in prior_messages],
    ]
