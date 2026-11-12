"""Single-process conversation ownership. Only workers release running turns."""

import json
import logging
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

from fastapi import HTTPException
from sqlmodel import Session

from ..config import VALID_MODES
from ..db import chat_turns, conversations
from ..db.engine import get_engine

INTERRUPTED = "_Chat interrupted — resend your message to generate a full response._"
FAILED = "_Chat failed — resend your message to try again._"
# An unattended turn keeps running after the client leaves, so it needs a ceiling of its own.
MAX_TURN_SECONDS = 600
FLUSH_INTERVAL_S = 1.0


def _with_marker(partial: str, marker: str) -> str:
    return f"{partial.rstrip()}\n\n{marker}" if partial.strip() else marker


def _snapshot_events(backend, model: str | None = None) -> dict:
    """What the turn has done so far, readable at any moment (also after a crash)."""
    budget = getattr(backend, "_budget", None)
    events: dict = {}
    if model:
        events["model"] = model
    memories = list(getattr(budget, "memories", []) or [])
    if memories:
        events["memories"] = [{"category": c, "content": t} for c, t in memories]
    changes = list(getattr(budget, "changes", []) or [])
    if changes:
        events["plan_changes"] = changes
    proposals = list(getattr(budget, "profile_proposals", []) or [])
    if proposals:
        events["profile_proposals"] = proposals
    return events


def recover_interrupted_turns() -> None:
    """Startup: a turn still ``running`` belongs to a process that no longer exists."""
    with Session(get_engine()) as session:
        for row in chat_turns.running(session):
            message_id = conversations.save(
                session, "assistant", _with_marker(row.partial_text, INTERRUPTED), mode=row.mode
            )
            chat_turns.update(
                session, row.id, status="interrupted", assistant_message_id=message_id
            )


@dataclass(eq=False)
class Turn:
    mode: str
    backend: object = None
    cancel: threading.Event = field(default_factory=threading.Event)
    tokens: queue.Queue = field(default_factory=queue.Queue)
    worker: threading.Thread | None = None
    turn_id: int | None = None
    started: float = field(default_factory=time.monotonic)


class ConversationCoordinator:
    def __init__(self, backend_factory: Callable):
        self._factory = backend_factory
        self._lock = threading.Lock()
        self._active: dict[str, Turn] = {}

    def acquire(self, mode: str) -> Turn:
        if mode not in VALID_MODES:
            raise HTTPException(400, f"mode must be one of {sorted(VALID_MODES)}")
        with self._lock:
            if mode in self._active:
                raise HTTPException(
                    409, "Your coach is already responding in this mode. Try again shortly."
                )
            turn = Turn(mode)
            self._active[mode] = turn
        try:
            turn.backend = self._factory(mode)
            return turn
        except BaseException:
            self.release(turn)
            raise

    def cancel(self, mode: str) -> bool:
        with self._lock:
            turn = self._active.get(mode)
        if turn is None:
            return False
        turn.cancel.set()
        return True

    def release(self, turn: Turn):
        with self._lock:
            if self._active.get(turn.mode) is turn:
                del self._active[turn.mode]

    def start(
        self,
        turn: Turn,
        system: str,
        message: str,
        saved_message: str,
        attachments,
        on_admitted=None,
    ):
        if turn.backend is not None:
            turn.backend.cancel_event = turn.cancel
        if hasattr(turn.backend, "prepare_turn"):
            try:
                system = turn.backend.prepare_turn(system, message, attachments)
            except ValueError as exc:
                import logging
                from ..budget import estimate

                logging.getLogger(__name__).info(
                    "chat_budget provider_model=%s input_estimate=%s rounds=0 tools=0 stop_reason=admission_rejected",
                    turn.backend.label,
                    estimate([system, message, attachments]),
                )
                raise HTTPException(413, str(exc)) from exc
        if on_admitted is not None:
            on_admitted()
        with Session(get_engine()) as session:
            user_id = conversations.save(session, "user", saved_message, mode=turn.mode)
            turn.turn_id = chat_turns.create(session, turn.mode, user_id)
        turn.worker = threading.Thread(
            target=self._run, args=(turn, system, message, attachments), daemon=True
        )
        turn.worker.start()

    def _run(self, turn, system, message, attachments):
        parts: list[str] = []
        last_flush = [0.0]
        session = Session(get_engine())
        finalized = False

        def check_cancel():
            if turn.cancel.is_set():
                raise InterruptedError("cancelled")
            if time.monotonic() - turn.started > MAX_TURN_SECONDS:
                turn.cancel.set()
                raise InterruptedError("turn exceeded its time limit")

        def flush(force=False):
            now = time.monotonic()
            if not force and now - last_flush[0] < FLUSH_INTERVAL_S:
                return
            last_flush[0] = now
            chat_turns.update(
                session,
                turn.turn_id,
                partial_text="".join(parts),
                events=_snapshot_events(turn.backend),
            )

        def on_token(chunk):
            check_cancel()
            parts.append(chunk)
            turn.tokens.put(chunk)
            try:
                flush()
            except Exception:  # a failed progress write must not kill the reply
                logging.getLogger(__name__).exception("chat turn progress write failed")
                session.rollback()

        try:
            try:
                check_cancel()
                turn.backend.cancel_event = turn.cancel
                text, memories, changes = turn.backend.stream_turn(
                    system, message, on_token, attachments=attachments
                )
                check_cancel()
                proposals = getattr(turn.backend, "take_profile_proposals", list)()
                events = _snapshot_events(turn.backend, turn.backend.label)
                # The returned values are authoritative; the snapshot only covers crashes.
                events["memories"] = [{"category": c, "content": t} for c, t in memories]
                events["plan_changes"] = changes
                events["profile_proposals"] = proposals
                events = {k: v for k, v in events.items() if v}
                message_id = conversations.save(
                    session, "assistant", text, mode=turn.mode, model=turn.backend.label
                )
                finalized = True  # the reply is stored; never write a second one below
                chat_turns.update(
                    session,
                    turn.turn_id,
                    status="done",
                    partial_text=text,
                    events=events,
                    assistant_message_id=message_id,
                )
                turn.tokens.put(f"[MODEL]{turn.backend.label}")
                if memories:
                    turn.tokens.put("[MEMORIES]" + json.dumps(events["memories"]))
                if changes:
                    turn.tokens.put("[PLAN_UPDATED]" + json.dumps(changes))
                if proposals:
                    turn.tokens.put("[PROFILE_PROPOSAL]" + json.dumps(proposals))
            except Exception as exc:
                session.rollback()
                if finalized:
                    logging.getLogger(__name__).exception("chat turn status write failed")
                    raise
                cancelled = turn.cancel.is_set() or isinstance(exc, InterruptedError)
                marker = INTERRUPTED if cancelled else FAILED
                partial = "".join(parts)
                message_id = conversations.save(
                    session, "assistant", _with_marker(partial, marker), mode=turn.mode
                )
                chat_turns.update(
                    session,
                    turn.turn_id,
                    status="cancelled" if cancelled else "failed",
                    partial_text=partial,
                    events=_snapshot_events(turn.backend),
                    assistant_message_id=message_id,
                )
                finalized = True
                if marker == FAILED:
                    turn.tokens.put(f"[ERROR]{exc}")
        finally:
            session.close()
            try:  # a row must never stay "running" once its worker is gone
                with Session(get_engine()) as last:
                    row = last.get(chat_turns.ChatTurn, turn.turn_id)
                    if row is not None and row.status == "running":
                        chat_turns.update(last, turn.turn_id, status="failed")
            except Exception:
                logging.getLogger(__name__).exception("could not close chat turn row")
            # Provider contexts have unwound and persistence has finished before admission reopens.
            self.release(turn)
            turn.tokens.put(None)
