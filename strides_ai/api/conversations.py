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
from ..db import chat_turns, conversations, mutations
from ..db.engine import get_engine
from ..turn_notice import notice_text, receipt_text

# An unattended turn keeps running after the client leaves, so it needs a ceiling of its own. The
# backend ends a slow turn itself (stop code "deadline", with its receipt); this is the backstop
# for one that does not, and is only used when the backend has no limits to read.
MAX_TURN_SECONDS = 600
FLUSH_INTERVAL_S = 1.0


def _backstop_seconds(turn) -> float:
    """The backend's turn deadline plus the idle timeout that can still be pending after it."""
    limits = getattr(turn.backend, "_limits", None)
    if limits is None:
        return MAX_TURN_SECONDS
    return limits.turn_deadline_s + limits.stream_idle_s


def _store_reply(session, mode, turn_id, text, notice=None, model=None) -> tuple[int, dict | None]:
    """The one place a reply is stored: its words, how it ended and what it changed, together.

    The receipt is built from the mutation log, so it is right however the turn ended.
    """
    receipt = mutations.build_receipt(session, turn_id)
    message_id = conversations.save(
        session, "assistant", text, mode=mode, model=model, notice=notice, receipt=receipt
    )
    return message_id, receipt


def _notice_event(code: str, receipt: dict | None, detail: str | None = None) -> str:
    return "[NOTICE]" + json.dumps(
        {
            "code": code,
            "text": notice_text(code),
            "receipt_text": receipt_text(receipt),
            "detail": detail,
        }
    )


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


def _turn_record(turn) -> dict | None:
    """The turn's record for storage, or None. A record must never cost the turn its reply."""
    try:
        record = getattr(getattr(turn.backend, "_budget", None), "record", None)
        if record is None:
            return None
        return record.to_dict(total_ms=int(round((time.monotonic() - turn.started) * 1000)))
    except Exception:
        logging.getLogger(__name__).exception("chat turn record could not be built")
        return None


def recover_interrupted_turns() -> None:
    """Startup: a turn still ``running`` belongs to a process that no longer exists."""
    with Session(get_engine()) as session:
        for row in chat_turns.running(session):
            message_id, _ = _store_reply(session, row.mode, row.id, row.partial_text, "interrupted")
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
                # A rejected message has no turn row, so its record is this one log line.
                logging.getLogger(__name__).info(
                    "chat_admission_rejected %s",
                    json.dumps(
                        {
                            "model": turn.backend.label,
                            "mode": turn.mode,
                            "reason": str(exc),
                            "est_input": estimate([system, message, attachments]),
                        }
                    ),
                )
                raise HTTPException(413, str(exc)) from exc
        if on_admitted is not None:
            on_admitted()
        with Session(get_engine()) as session:
            user_id = conversations.save(session, "user", saved_message, mode=turn.mode)
            turn.turn_id = chat_turns.create(session, turn.mode, user_id)
        if turn.backend is not None:
            turn.backend.turn_id = turn.turn_id  # lets its writes be logged against this turn
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
            if time.monotonic() - turn.started > _backstop_seconds(turn):
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
                notice = getattr(getattr(turn.backend, "_budget", None), "notice", None)
                message_id, receipt = _store_reply(
                    session, turn.mode, turn.turn_id, text, notice, turn.backend.label
                )
                finalized = True  # the reply is stored; never write a second one below
                chat_turns.update(
                    session,
                    turn.turn_id,
                    status="done",
                    partial_text=text,
                    events=events,
                    assistant_message_id=message_id,
                    budget=_turn_record(turn),
                )
                turn.tokens.put(f"[MODEL]{turn.backend.label}")
                if memories:
                    turn.tokens.put("[MEMORIES]" + json.dumps(events["memories"]))
                if changes:
                    turn.tokens.put("[PLAN_UPDATED]" + json.dumps(changes))
                if proposals:
                    turn.tokens.put("[PROFILE_PROPOSAL]" + json.dumps(proposals))
                if notice:
                    turn.tokens.put(_notice_event(notice, receipt))
            except Exception as exc:
                session.rollback()
                if finalized:
                    logging.getLogger(__name__).exception("chat turn status write failed")
                    raise
                cancelled = turn.cancel.is_set() or isinstance(exc, InterruptedError)
                code = "interrupted" if cancelled else "failed"
                partial = "".join(parts)
                message_id, receipt = _store_reply(session, turn.mode, turn.turn_id, partial, code)
                events = _snapshot_events(turn.backend)
                chat_turns.update(
                    session,
                    turn.turn_id,
                    status="cancelled" if cancelled else "failed",
                    partial_text=partial,
                    events=events,
                    assistant_message_id=message_id,
                    budget=_turn_record(turn),
                )
                finalized = True
                # What was saved before the stop is shown too, not only the failure.
                if events.get("memories"):
                    turn.tokens.put("[MEMORIES]" + json.dumps(events["memories"]))
                if events.get("plan_changes"):
                    turn.tokens.put("[PLAN_UPDATED]" + json.dumps(events["plan_changes"]))
                if events.get("profile_proposals"):
                    turn.tokens.put("[PROFILE_PROPOSAL]" + json.dumps(events["profile_proposals"]))
                turn.tokens.put(_notice_event(code, receipt, None if cancelled else str(exc)))
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
