"""Coaching chat loop — backend-agnostic."""

import sqlite3

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

from .backends.base import BaseBackend
from .db import get_all_activities, get_all_memories, get_recent_messages, RUN_TYPES
from . import db

RECALL_MESSAGES = 40

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

The athlete's full training log is embedded in the next message as structured \
text. Treat it as ground truth for all data-related questions.

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

The athlete's full training log is embedded in the next message as structured \
text. Treat it as ground truth for all data-related questions.

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

The athlete's full training log is embedded in the next message as structured \
text. Treat it as ground truth for all data-related questions.

**Memory:** Use the save_memory tool proactively whenever the athlete mentions \
goals, upcoming events, injuries, preferences, or any key context that should \
persist across sessions.\
"""

_PROMPT_BY_MODE = {
    "running": RUNNING_SYSTEM_PROMPT,
    "cycling": CYCLING_SYSTEM_PROMPT,
    "hybrid": HYBRID_SYSTEM_PROMPT,
}


def build_system(profile: str, memories: list[dict], mode: str = "running") -> str:
    prompt = _PROMPT_BY_MODE.get(mode, RUNNING_SYSTEM_PROMPT)

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
        prompt += "\n\n## Upcoming Planned Workouts (next 14 days)\n" + header + "\n" + sep + "\n" + "\n".join(rows)

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
        header = "DATE       | TYPE       | NAME                           | DIST(km) | DURATION | PACE/SPEED  | AVG HR | MAX HR | CADENCE | ELEV(m) | SUFFER | RPE"
        sep = "-" * 150
    elif mode == "cycling":
        header = "DATE       | NAME                           | DIST(km) | DURATION | SPEED    | AVG HR | MAX HR | CADENCE(rpm) | ELEV(m) | SUFFER | RPE"
        sep = "-" * 135
    else:
        header = "DATE       | NAME                           | DIST(km) | DURATION | PACE     | AVG HR | MAX HR | CADENCE(spm) | ELEV(m) | SUFFER | RPE"
        sep = "-" * 135

    lines = [header, sep]

    for r in rows:
        dist_km = (r["distance_m"] or 0) / 1000
        sport = r["sport_type"] or ""
        is_run = sport in RUN_TYPES

        if mode == "hybrid":
            pace_speed = _format_pace(r["avg_pace_s_per_km"]) if is_run else _format_speed(r["avg_pace_s_per_km"])
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
                f"{r['perceived_exertion'] or '—'}"
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
                f"{r['perceived_exertion'] or '—'}"
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
                f"{r['perceived_exertion'] or '—'}"
            )

    total_km = sum((r["distance_m"] or 0) / 1000 for r in rows)
    act_label = "runs" if mode == "running" else "rides" if mode == "cycling" else "activities"
    lines.append(sep)
    lines.append(f"Total: {len(rows)} {act_label}, {total_km:.1f} km")
    return "\n".join(lines)


def build_initial_history(activities, prior_messages: list[dict], mode: str = "running") -> list[dict]:
    """
    Build the seed history passed to each backend on construction:
    training-log injection followed by any recalled prior messages.
    """
    training_log = build_training_log(activities, mode)
    log_message = f"Here is the athlete's complete training log:\n\n```\n{training_log}\n```"
    act_label = "runs" if mode == "running" else "rides" if mode == "cycling" else "activities"
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


def chat(backend: BaseBackend, profile: str, mode: str = "running") -> None:
    """Interactive coaching chat loop."""
    console = Console()

    memories = get_all_memories()
    system = build_system(profile, memories, mode=mode)

    prior_messages = get_recent_messages(RECALL_MESSAGES, mode=mode)
    mem_summary = f"{len(memories)} memor{'y' if len(memories) == 1 else 'ies'}" if memories else "no memories yet"
    hist_summary = f"{len(prior_messages)} messages recalled" if prior_messages else "new session"

    console.print(
        Panel(
            f"[bold green]Strides AI Coach[/bold green]\n"
            f"[dim]{mem_summary} · {hist_summary} · {backend.label}[/dim]\n\n"
            "Type your question and press Enter. "
            "Type [bold]exit[/bold] or [bold]quit[/bold] to leave.",
            expand=False,
        )
    )

    while True:
        try:
            user_input = Prompt.ask("\n[bold cyan]You[/bold cyan]").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Goodbye![/dim]")
            break

        if user_input.lower() in {"exit", "quit", "q"}:
            console.print("[dim]Goodbye![/dim]")
            break
        if not user_input:
            continue

        console.print("\n[bold magenta]Coach[/bold magenta]")

        def on_token(chunk: str) -> None:
            console.print(chunk, end="", markup=False)

        response_text, memories_saved = backend.stream_turn(system, user_input, on_token)
        console.print()

        if memories_saved:
            tags = " · ".join(f"[{cat}] {content}" for cat, content in memories_saved)
            console.print(f"[dim italic]Remembered: {tags}[/dim italic]")

        db.save_message("user", user_input, mode=mode)
        db.save_message("assistant", response_text, mode=mode)
