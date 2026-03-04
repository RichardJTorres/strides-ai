"""Coaching chat loop — backend-agnostic."""

import sqlite3

from .backends.base import BaseBackend
from .db import get_all_activities, get_all_memories, get_recent_messages
from . import db

RECALL_MESSAGES = 40

BASE_SYSTEM_PROMPT = """\
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


def build_system(profile: str, memories: list[dict]) -> str:
    prompt = BASE_SYSTEM_PROMPT

    if profile:
        prompt += f"\n\n{profile}"

    if memories:
        lines = [f"  [{m['category']}] {m['content']}" for m in memories]
        prompt += "\n\n## Coaching Notes (remembered from previous sessions)\n" + "\n".join(lines)

    return prompt


def _format_pace(s_per_km: float | None) -> str:
    if s_per_km is None:
        return "—"
    mins = int(s_per_km // 60)
    secs = int(s_per_km % 60)
    return f"{mins}:{secs:02d}/km"


def _format_duration(seconds: int | None) -> str:
    if seconds is None:
        return "—"
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h{m:02d}m{s:02d}s"
    return f"{m}m{s:02d}s"


def build_training_log(rows: list[sqlite3.Row]) -> str:
    if not rows:
        return "No activities found."

    lines = ["DATE       | NAME                           | DIST(km) | DURATION | PACE     | AVG HR | MAX HR | CADENCE | ELEV(m) | SUFFER | RPE"]
    lines.append("-" * 130)

    for r in rows:
        dist_km = (r["distance_m"] or 0) / 1000
        lines.append(
            f"{r['date'] or '?':10s} | "
            f"{(r['name'] or '')[:30]:30s} | "
            f"{dist_km:8.2f} | "
            f"{_format_duration(r['moving_time_s']):8s} | "
            f"{_format_pace(r['avg_pace_s_per_km']):8s} | "
            f"{r['avg_hr'] or '—':6} | "
            f"{r['max_hr'] or '—':6} | "
            f"{r['avg_cadence'] or '—':7} | "
            f"{r['elevation_gain_m'] or '—':7} | "
            f"{r['suffer_score'] or '—':6} | "
            f"{r['perceived_exertion'] or '—'}"
        )

    total_km = sum((r["distance_m"] or 0) / 1000 for r in rows)
    lines.append("-" * 130)
    lines.append(f"Total: {len(rows)} runs, {total_km:.1f} km")
    return "\n".join(lines)


def build_initial_history(activities, prior_messages: list[dict]) -> list[dict]:
    """
    Build the seed history passed to each backend on construction:
    training-log injection followed by any recalled prior messages.
    """
    training_log = build_training_log(activities)
    log_message = f"Here is the athlete's complete training log:\n\n```\n{training_log}\n```"
    return [
        {"role": "user", "content": log_message},
        {
            "role": "assistant",
            "content": (
                f"Got it — I have your full training log loaded ({len(activities)} runs). "
                "What would you like to discuss?"
            ),
        },
        *prior_messages,
    ]


def chat(backend: BaseBackend, profile: dict) -> None:
    """Interactive coaching chat loop."""
    from rich.console import Console
    from rich.panel import Panel
    from rich.prompt import Prompt

    console = Console()

    memories = get_all_memories()
    system = build_system(profile, memories)

    prior_messages = get_recent_messages(RECALL_MESSAGES)
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

        db.save_message("user", user_input)
        db.save_message("assistant", response_text)
