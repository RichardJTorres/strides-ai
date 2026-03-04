"""Claude-powered coaching chat with persistent memory and conversation history."""

import sqlite3

import anthropic

from . import db
from .db import get_all_activities, get_all_memories, get_recent_messages

MODEL = "claude-sonnet-4-6"
RECALL_MESSAGES = 40  # previous messages reloaded from DB on startup

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

SAVE_MEMORY_TOOL = {
    "name": "save_memory",
    "description": (
        "Save an important fact about the athlete to persistent memory. "
        "Call this whenever the athlete mentions: goals, target races or times, "
        "injuries or niggles, training preferences, weekly mileage targets, "
        "or any coaching context that should be remembered in future sessions."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "category": {
                "type": "string",
                "enum": ["goal", "race", "injury", "preference", "training", "other"],
                "description": "Category of the memory",
            },
            "content": {
                "type": "string",
                "description": "The fact to remember, as a clear concise statement",
            },
        },
        "required": ["category", "content"],
    },
}


def _build_system(memories: list[dict]) -> str:
    prompt = BASE_SYSTEM_PROMPT
    if memories:
        lines = [f"  [{m['category']}] {m['content']}" for m in memories]
        prompt += (
            "\n\n## Athlete Profile (remembered from previous sessions)\n"
            + "\n".join(lines)
        )
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


def _build_training_log(rows: list[sqlite3.Row]) -> str:
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


def _content_text(content) -> str:
    """Extract plain text from a message content (str or list of content blocks)."""
    if isinstance(content, str):
        return content
    return "".join(
        block.text
        for block in content
        if hasattr(block, "type") and block.type == "text"
    )


def _run_turn(
    client: anthropic.Anthropic,
    console,
    history: list[dict],
    system: str,
) -> str:
    """
    Stream one assistant turn, transparently handling save_memory tool calls.
    Appends all assistant and tool-result messages to *history* in-place.
    Returns all text emitted during the turn.
    """
    response_text = ""

    while True:
        with client.messages.stream(
            model=MODEL,
            max_tokens=2048,
            system=system,
            messages=history,
            tools=[SAVE_MEMORY_TOOL],
        ) as stream:
            for chunk in stream.text_stream:
                console.print(chunk, end="", markup=False)
                response_text += chunk
            final = stream.get_final_message()

        history.append({"role": "assistant", "content": final.content})

        if final.stop_reason != "tool_use":
            break

        # Execute tool calls and feed results back
        tool_results = []
        saved = []
        for block in final.content:
            if not (hasattr(block, "type") and block.type == "tool_use"):
                continue
            if block.name == "save_memory":
                result = db.save_memory(block.input["category"], block.input["content"])
                saved.append(f"[{block.input['category']}] {block.input['content']}")
                tool_results.append(
                    {"type": "tool_result", "tool_use_id": block.id, "content": result}
                )

        if saved:
            console.print(
                f"\n[dim italic]Remembered: {' · '.join(saved)}[/dim italic]"
            )

        history.append({"role": "user", "content": tool_results})

    return response_text


def chat(api_key: str) -> None:
    """Interactive coaching chat loop."""
    from rich.console import Console
    from rich.panel import Panel
    from rich.prompt import Prompt

    console = Console()
    client = anthropic.Anthropic(api_key=api_key)

    # Load persisted state
    activities = get_all_activities()
    memories = get_all_memories()
    prior_messages = get_recent_messages(RECALL_MESSAGES)

    system = _build_system(memories)

    training_log = _build_training_log(activities)
    log_message = f"Here is the athlete's complete training log:\n\n```\n{training_log}\n```"

    # Seed history: fresh training log + any recalled prior conversation
    history: list[dict] = [
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

    mem_summary = f"{len(memories)} memor{'y' if len(memories) == 1 else 'ies'}" if memories else "no memories yet"
    hist_summary = f"{len(prior_messages)} messages recalled" if prior_messages else "new session"
    console.print(
        Panel(
            f"[bold green]Strides AI Coach[/bold green]\n"
            f"[dim]{len(activities)} runs · {mem_summary} · {hist_summary} · {MODEL}[/dim]\n\n"
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

        history.append({"role": "user", "content": user_input})

        console.print("\n[bold magenta]Coach[/bold magenta]")
        response_text = _run_turn(client, console, history, system)
        console.print()

        # Persist this exchange to DB
        db.save_message("user", user_input)
        db.save_message("assistant", response_text)
