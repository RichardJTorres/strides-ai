"""Single-process conversation ownership. Only workers release running turns."""

import json
import queue
import threading
from dataclasses import dataclass, field
from typing import Callable

from fastapi import HTTPException
from sqlmodel import Session

from ..config import VALID_MODES
from ..db import conversations
from ..db.engine import get_engine

INTERRUPTED = "_Chat interrupted — resend your message to generate a full response._"
FAILED = "_Chat failed — resend your message to try again._"


@dataclass(eq=False)
class Turn:
    mode: str
    backend: object = None
    cancel: threading.Event = field(default_factory=threading.Event)
    tokens: queue.Queue = field(default_factory=queue.Queue)
    worker: threading.Thread | None = None


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
            conversations.save(session, "user", saved_message, mode=turn.mode)
        turn.worker = threading.Thread(
            target=self._run, args=(turn, system, message, attachments), daemon=True
        )
        turn.worker.start()

    def _run(self, turn, system, message, attachments):
        def check_cancel():
            if turn.cancel.is_set():
                raise InterruptedError("client disconnected")

        def on_token(chunk):
            check_cancel()
            turn.tokens.put(chunk)

        try:
            with Session(get_engine()) as session:
                try:
                    check_cancel()
                    turn.backend.cancel_event = turn.cancel
                    text, memories, changes = turn.backend.stream_turn(
                        system, message, on_token, attachments=attachments
                    )
                    check_cancel()
                    conversations.save(
                        session, "assistant", text, mode=turn.mode, model=turn.backend.label
                    )
                    turn.tokens.put(f"[MODEL]{turn.backend.label}")
                    if memories:
                        turn.tokens.put(
                            "[MEMORIES]"
                            + json.dumps([{"category": c, "content": t} for c, t in memories])
                        )
                    if changes:
                        turn.tokens.put("[PLAN_UPDATED]" + json.dumps(changes))
                    proposals = getattr(turn.backend, "take_profile_proposals", list)()
                    if proposals:
                        turn.tokens.put("[PROFILE_PROPOSAL]" + json.dumps(proposals))
                except Exception as exc:
                    session.rollback()
                    marker = (
                        INTERRUPTED
                        if turn.cancel.is_set() or isinstance(exc, InterruptedError)
                        else FAILED
                    )
                    conversations.save(session, "assistant", marker, mode=turn.mode)
                    if marker == FAILED:
                        turn.tokens.put(f"[ERROR]{exc}")
        finally:
            # Provider contexts have unwound and persistence has finished before admission reopens.
            self.release(turn)
            turn.tokens.put(None)
