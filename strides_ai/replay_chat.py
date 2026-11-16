"""Replay a fixed set of coach questions against a COPY of the database and report how each ended.

Acceptance for the turn policy and the context builder: every prompt should end ``complete``, any
calendar writes should be valid, and the record should show the expected sections. A run calls a
real provider (it costs money, roughly $2 on a frontier model), so nothing is sent unless
``--confirm-cost`` is given; without it the prompts are only listed.

Nothing here touches the real database. ``main`` points ``STRIDES_DATA_DIR`` at a temporary
directory before the app's configuration is imported, copies the source database into it with
SQLite's backup API (the source is opened read-only), and refuses to run if the engine is not
using that copy. Keep this module's top-level imports free of ``strides_ai.config`` for that
reason.
"""

import argparse
import json
import os
import queue
import sqlite3
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from types import SimpleNamespace


@dataclass(frozen=True)
class ReplayPrompt:
    id: str
    mode: str
    message: str
    # True: must change the calendar. False: must not. None: either is fine.
    expect_writes: bool | None = None


# Real coach questions. The first two are the ones that failed: a multi-step "schedule a block"
# request, and the bare follow-up that confirmed it (so they must stay adjacent and in order).
REPLAY_PROMPTS: tuple[ReplayPrompt, ...] = (
    ReplayPrompt(
        "block",
        "running",
        "Schedule me a four-week training block towards my next race: four runs a week, a long run "
        "on Sunday, a down week at the end, and put every workout on my calendar.",
        expect_writes=True,
    ),
    ReplayPrompt("block_followup", "running", "Yes, let's do that."),
    ReplayPrompt("last_run", "running", "How did my last run go? Anything I should change?"),
    ReplayPrompt(
        "ramp", "running", "Am I ramping my weekly mileage too fast? Be specific about the numbers."
    ),
    ReplayPrompt(
        "knee",
        "running",
        "My left knee has been sore for three days. What should I change this week?",
    ),
    ReplayPrompt(
        "memory",
        "running",
        "Remember that I can't train on Wednesdays because of work.",
    ),
    ReplayPrompt(
        "move",
        "running",
        "Move my long run this week to Saturday and make Thursday a rest day.",
        expect_writes=True,
    ),
    ReplayPrompt(
        "fuel",
        "running",
        "What should I eat before and during my next long run?",
        expect_writes=False,
    ),
    ReplayPrompt(
        "trend",
        "hybrid",
        "How has my training trended over the last eight weeks?",
        expect_writes=False,
    ),
    ReplayPrompt(
        "week",
        "cycling",
        "Give me a quick summary of my week and what is next.",
        expect_writes=False,
    ),
)


@dataclass
class PromptResult:
    id: str
    mode: str
    status: str = "not run"  # done | failed | cancelled | rejected | timeout
    stop_reason: str | None = None
    notice: str | None = None
    complete: bool = False
    writes: dict = field(default_factory=lambda: {"created": 0, "updated": 0, "deleted": 0})
    writes_valid: bool = True
    write_problems: list = field(default_factory=list)
    sections_sent: list = field(default_factory=list)
    sections_left_out: list = field(default_factory=list)
    est_input: int | None = None
    total_ms: int | None = None
    rounds: list = field(default_factory=list)
    reply: str = ""
    problems: list = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


def section_sent(section: dict) -> bool:
    """Required sections are always sent; a reducible one is left out when it rendered empty."""
    return section.get("kind") == "required" or section.get("bytes", 0) > 0


def copy_database(source: Path, dest_dir: Path) -> Path:
    """A consistent copy of ``source`` in ``dest_dir``; the source is opened read-only."""
    source = Path(source).expanduser()
    if not source.is_file():
        raise FileNotFoundError(f"No database at {source}")
    dest = Path(dest_dir) / "activities.db"
    if dest.resolve() == source.resolve():
        raise ValueError("The copy must not be the source database")
    reader = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    try:
        writer = sqlite3.connect(dest)
        try:
            reader.backup(writer)
        finally:
            writer.close()
    finally:
        reader.close()
    return dest


def _check_calendar_writes(receipt: dict | None) -> tuple[dict, list[str]]:
    """Counts of what a turn wrote to the calendar, and a problem for each invalid entry."""
    from sqlmodel import Session

    from .db.engine import get_engine
    from .db.models import CalendarEntry, WorkoutDetail
    from .kinds import KIND_WORKOUT, KINDS, WORKOUT_TYPES

    counts = {"created": 0, "updated": 0, "deleted": 0}
    problems: list[str] = []
    calendar = next(
        (c for c in (receipt or {}).get("committed", []) if c.get("kind") == "calendar"), None
    )
    if calendar is None:
        return counts, problems
    created_ids = [c.get("id") for c in calendar.get("created", [])]
    counts["created"] = len(created_ids)
    counts["updated"] = len(calendar.get("updated", []))
    counts["deleted"] = len(calendar.get("deleted", []))
    with Session(get_engine()) as session:
        for entry_id in [*created_ids, *calendar.get("updated", [])]:
            entry = session.get(CalendarEntry, entry_id)
            if entry is None:
                problems.append(f"entry {entry_id} was reported written but does not exist")
                continue
            try:
                date.fromisoformat(entry.date)
            except (TypeError, ValueError):
                problems.append(f"entry {entry_id} has a bad date {entry.date!r}")
            if entry.kind not in KINDS:
                problems.append(f"entry {entry_id} has an unknown kind {entry.kind!r}")
            if entry.kind == KIND_WORKOUT:
                detail = session.get(WorkoutDetail, entry_id)
                if detail is None or detail.workout_type not in WORKOUT_TYPES:
                    problems.append(f"entry {entry_id} has no valid workout type")
    return counts, problems


def run_prompt(prompt: ReplayPrompt, coordinator, build_system, timeout_s: float) -> PromptResult:
    """Send one prompt through the same coordinator path a chat request takes."""
    from fastapi import HTTPException
    from sqlmodel import Session

    from .db import chat_turns
    from .db.engine import get_engine
    from .db.models import Conversation

    result = PromptResult(prompt.id, prompt.mode)
    turn = coordinator.acquire(prompt.mode)
    try:
        with Session(get_engine()) as session:
            system = build_system(session, prompt.mode)
        coordinator.start(turn, system, prompt.message, prompt.message, None)
    except HTTPException as exc:  # admission rejected the message before anything was saved
        coordinator.release(turn)
        result.status, result.problems = "rejected", [f"rejected ({exc.status_code}): {exc.detail}"]
        return result
    except BaseException:
        coordinator.release(turn)
        raise
    turn.worker.join(timeout_s)
    if turn.worker.is_alive():
        turn.cancel.set()
        turn.worker.join(30)
        result.status = "timeout"
        result.problems.append(f"no result within {timeout_s:.0f}s")
    chunks = []
    while True:
        try:
            chunks.append(turn.tokens.get_nowait())
        except queue.Empty:
            break

    with Session(get_engine()) as session:
        row = session.get(chat_turns.ChatTurn, turn.turn_id)
        record = chat_turns.budget(row) or {}
        if result.status != "timeout":
            result.status = row.status
        message = (
            session.get(Conversation, row.assistant_message_id)
            if row.assistant_message_id
            else None
        )
    result.reply = getattr(message, "content", "") or ""
    result.notice = getattr(message, "notice", None)
    receipt = None
    if message is not None and getattr(message, "receipt_json", None):
        receipt = json.loads(message.receipt_json)
    result.stop_reason = (record.get("stop") or {}).get("reason")
    result.complete = result.status == "done" and result.stop_reason == "complete"
    result.est_input = record.get("est_input")
    result.total_ms = record.get("total_ms")
    sections = record.get("sections") or []
    result.sections_sent = [s["key"] for s in sections if section_sent(s)]
    result.sections_left_out = [s["key"] for s in sections if not section_sent(s)]
    result.rounds = [
        {
            k: r.get(k)
            for k in (
                "kind",
                "est_input",
                "input_total",
                "cache_read",
                "output_total",
                "first_event_ms",
                "first_text_ms",
                "duration_ms",
                "tools_run",
                "stop",
            )
        }
        for r in record.get("rounds", [])
    ]
    result.writes, result.write_problems = _check_calendar_writes(receipt)
    result.writes_valid = not result.write_problems

    wrote = sum(result.writes.values()) > 0
    if not result.complete:
        result.problems.append(
            f"ended {result.stop_reason or result.status}"
            + (f" (notice {result.notice})" if result.notice else "")
        )
    result.problems += result.write_problems
    if prompt.expect_writes is True and not wrote:
        result.problems.append("expected calendar changes, found none")
    if prompt.expect_writes is False and wrote:
        result.problems.append("changed the calendar when it should not have")
    if not result.reply.strip():
        result.problems.append("no reply text")
    return result


def run_replay(
    prompts, *, backend_factory, expected_db: Path, build_system=None, timeout_s: float = 900
) -> list[PromptResult]:
    """Run ``prompts`` in order against the database the engine is using, which must be
    ``expected_db`` (the copy): the replay refuses to run against anything else."""
    from .api.conversations import ConversationCoordinator
    from .db import engine

    if Path(engine.DB_PATH).resolve() != Path(expected_db).resolve():
        raise RuntimeError(
            f"The engine uses {engine.DB_PATH}, not the copy {expected_db}; refusing to run."
        )
    if build_system is None:
        from .api.routers.chat import _build_chat_system as build_system
    coordinator = ConversationCoordinator(backend_factory)
    return [run_prompt(p, coordinator, build_system, timeout_s) for p in prompts]


def format_results(results: list[PromptResult]) -> str:
    lines = [
        f"{'prompt':<16}{'mode':<9}{'stop':<16}{'writes c/u/d':<14}{'rounds':>6}"
        f"{'est_in':>9}{'total_s':>9}  result",
    ]
    for r in results:
        w = r.writes
        lines.append(
            f"{r.id:<16}{r.mode:<9}{(r.stop_reason or r.status):<16}"
            f"{w['created']}/{w['updated']}/{w['deleted']:<10}{len(r.rounds):>6}"
            f"{(r.est_input if r.est_input is not None else ''):>9}"
            f"{(round(r.total_ms / 1000, 1) if r.total_ms is not None else ''):>9}  "
            + ("ok" if r.ok else "PROBLEM: " + "; ".join(r.problems))
        )
        sent = ", ".join(r.sections_sent) or "-"
        left = ", ".join(r.sections_left_out)
        lines.append(f"    sections sent: {sent}" + (f" | left out: {left}" if left else ""))
        for i, rd in enumerate(r.rounds, 1):
            lines.append(
                f"    round {i} {rd['kind']:<5} first_event={rd['first_event_ms']}ms "
                f"first_text={rd['first_text_ms']}ms duration={rd['duration_ms']}ms "
                f"in={rd['input_total'] or rd['est_input']} cache_read={rd['cache_read']} "
                f"out={rd['output_total']} tools={rd['tools_run']} stop={rd['stop']}"
            )
    bad = [r.id for r in results if not r.ok]
    lines.append("")
    lines.append(
        "All prompts ended complete with valid calendar writes."
        if not bad
        else f"{len(bad)} of {len(results)} prompts need a look: {', '.join(bad)}"
    )
    return "\n".join(lines)


def _select(only: str | None) -> list[ReplayPrompt]:
    if not only:
        return list(REPLAY_PROMPTS)
    wanted = [i.strip() for i in only.split(",") if i.strip()]
    unknown = set(wanted) - {p.id for p in REPLAY_PROMPTS}
    if unknown:
        raise SystemExit(f"Unknown prompt ids: {', '.join(sorted(unknown))}")
    return [p for p in REPLAY_PROMPTS if p.id in wanted]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--source",
        default="~/.strides_ai/activities.db",
        help="database to copy (opened read-only; never modified)",
    )
    parser.add_argument("--provider", help="claude | gemini | openai | ollama (default: .env)")
    parser.add_argument("--only", help="comma-separated prompt ids; a follow-up needs its block")
    parser.add_argument(
        "--json", dest="json_path", help="also write the full results (with replies)"
    )
    parser.add_argument(
        "--confirm-cost",
        action="store_true",
        help="really call the provider (costs money); without it the prompts are only listed",
    )
    args = parser.parse_args(argv)
    prompts = _select(args.only)

    if not args.confirm_cost:
        print("Dry run: nothing was sent. These prompts would run, in order, on a database copy:")
        for p in prompts:
            print(f"  [{p.mode}] {p.id}: {p.message}")
        print("Add --confirm-cost to call the provider (roughly $2 on a frontier model).")
        return 0

    if "strides_ai.config" in sys.modules:
        raise SystemExit("strides_ai.config was imported first; start this as a fresh process")
    workdir = Path(tempfile.mkdtemp(prefix="strides_replay_"))
    os.environ["STRIDES_DATA_DIR"] = str(workdir)  # before the app's configuration is read
    copy = copy_database(Path(args.source), workdir)
    print(f"Working on a copy: {copy}")

    from . import db
    from .api.deps import build_backend

    db.init_db()  # migrations run on the copy
    app = SimpleNamespace(state=SimpleNamespace(provider=args.provider))
    results = run_replay(
        prompts,
        backend_factory=lambda mode: build_backend(app, mode),
        expected_db=copy,
    )
    print(format_results(results))
    if args.json_path:
        Path(args.json_path).write_text(json.dumps([asdict(r) for r in results], indent=2))
        print(f"Full results written to {args.json_path}")
    return 0 if all(r.ok for r in results) else 1
