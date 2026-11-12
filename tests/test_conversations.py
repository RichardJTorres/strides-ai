"""Deterministic admission and worker lifecycle tests (no provider calls)."""

import threading

import pytest
from fastapi import HTTPException

from strides_ai import db
from strides_ai.api.conversations import ConversationCoordinator, FAILED, INTERRUPTED


class FakeBackend:
    label = "captured-model"

    def __init__(self, entered, finish, fail=False):
        self.entered, self.finish, self.fail = entered, finish, fail

    def stream_turn(self, system, message, on_token, attachments=None):
        self.entered.set()
        assert self.finish.wait(5)
        if self.fail:
            raise RuntimeError("provider failed")
        on_token(message)
        return "reply:" + message, [], []


def test_admission_and_parallel_modes(tmp_db):
    entered, finish = threading.Event(), threading.Event()
    histories = []

    def factory(mode):
        histories.append((mode, db.get_recent_messages(mode=mode)))
        return FakeBackend(entered, finish)

    coordinator = ConversationCoordinator(factory)
    running = coordinator.acquire("running")
    coordinator.start(running, "running prompt", "run", "run", None)
    assert entered.wait(2)
    with pytest.raises(HTTPException) as exc:
        coordinator.acquire("running")
    assert exc.value.status_code == 409
    with pytest.raises(HTTPException) as exc:
        coordinator.acquire("invalid")
    assert exc.value.status_code == 400
    cycling = coordinator.acquire("cycling")
    coordinator.start(cycling, "cycling prompt", "ride", "ride", None)
    assert [m["content"] for m in db.get_recent_messages(mode="running")] == ["run"]
    assert len(histories) == 2
    assert all(history == [] for _, history in histories)
    finish.set()
    running.worker.join(3)
    cycling.worker.join(3)
    assert [m["content"] for m in db.get_recent_messages(mode="running")] == ["run", "reply:run"]
    assert [m["content"] for m in db.get_recent_messages(mode="cycling")] == ["ride", "reply:ride"]
    next_turn = coordinator.acquire("running")
    assert len(histories[-1][1]) == 2
    assert next_turn.backend is not running.backend
    coordinator.release(next_turn)


@pytest.mark.parametrize("cancel", [False, True])
def test_failure_and_delayed_cancellation(tmp_db, cancel):
    entered, finish = threading.Event(), threading.Event()
    coordinator = ConversationCoordinator(
        lambda mode: FakeBackend(entered, finish, fail=not cancel)
    )
    turn = coordinator.acquire("running")
    coordinator.start(turn, "prompt", "hello", "hello", None)
    assert entered.wait(2)
    if cancel:
        turn.cancel.set()
    with pytest.raises(HTTPException):
        coordinator.acquire("running")
    finish.set()
    turn.worker.join(3)
    assert not turn.worker.is_alive()
    history = db.get_recent_messages(mode="running")
    assert [m["content"] for m in history] == ["hello", INTERRUPTED if cancel else FAILED]
    coordinator.release(coordinator.acquire("running"))


def test_snapshot_survives_configuration_refresh(tmp_db):
    entered, finish = threading.Event(), threading.Event()
    config = {"model": "old"}

    def factory(mode):
        backend = FakeBackend(entered, finish)
        backend.label = config["model"]
        return backend

    coordinator = ConversationCoordinator(factory)
    turn = coordinator.acquire("running")
    coordinator.start(turn, "old profile", "hi", "hi", None)
    assert entered.wait(2)
    config["model"] = "new"
    assert turn.backend.label == "old"
    finish.set()
    turn.worker.join(3)
    next_turn = coordinator.acquire("running")
    assert next_turn.backend.label == "new"
    assert db.get_recent_messages(mode="running")[-1]["model"] == "old"
    coordinator.release(next_turn)


@pytest.mark.parametrize("mode, busy, status", [("invalid", False, 400), ("running", True, 409)])
def test_http_rejection_precedes_attachments_and_persistence(
    tmp_db, monkeypatch, mode, busy, status
):
    from unittest.mock import AsyncMock

    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from strides_ai.api.routers import chat

    factory_calls = []
    coordinator = ConversationCoordinator(lambda mode: factory_calls.append(mode))
    if busy:
        coordinator.acquire("running")
    app = FastAPI()
    app.state.conversations = coordinator
    app.include_router(chat.router)
    process = AsyncMock()
    monkeypatch.setattr(chat, "_process_attachment", process)
    client = TestClient(app)
    response = client.post(
        "/chat",
        data={"message": "reject me", "mode": mode},
        files={"files": ("photo.png", b"fake", "image/png")},
    )
    assert response.status_code == status
    process.assert_not_called()
    assert factory_calls == (["running"] if busy else [])
    assert db.get_recent_messages(mode="running") == []


def test_chat_attaches_activity_card_and_persists_short_display(tmp_db, sample_activity):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from strides_ai.api.routers import chat

    db.upsert_activity(sample_activity)
    captured = {}
    entered, finish = threading.Event(), threading.Event()

    class CapturingBackend:
        label = "fake"

        def stream_turn(self, system, message, on_token, attachments=None):
            captured["attachments"] = attachments
            entered.set()
            assert finish.wait(5)
            on_token("ok")
            return "ok", [], []

    coordinator = ConversationCoordinator(lambda mode: CapturingBackend())
    app = FastAPI()
    app.state.conversations = coordinator
    app.include_router(chat.router)
    client = TestClient(app)

    response = client.post(
        "/chat",
        data={"message": "how did this one go?", "mode": "running", "activity_ids": "1001"},
    )
    assert response.status_code == 200
    assert entered.wait(2)
    finish.set()

    attachments = captured["attachments"]
    assert len(attachments) == 1
    assert attachments[0]["type"] == "text"
    assert "## Attached Activity: Morning Run" in attachments[0]["text"]

    saved = db.get_recent_messages(mode="running")
    assert saved[0]["content"] == "how did this one go?\n\n📎 Activity: Morning Run (2025-06-15)"


def test_chat_unknown_activity_id_rejects_before_persisting(tmp_db):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from strides_ai.api.routers import chat

    factory_calls = []
    coordinator = ConversationCoordinator(lambda mode: factory_calls.append(mode))
    app = FastAPI()
    app.state.conversations = coordinator
    app.include_router(chat.router)
    client = TestClient(app)

    response = client.post(
        "/chat",
        data={"message": "hi", "mode": "running", "activity_ids": "999999"},
    )
    assert response.status_code == 404
    assert db.get_recent_messages(mode="running") == []
    # Turn was released despite the mid-handler rejection — a retry isn't blocked by a stale lock.
    coordinator.release(coordinator.acquire("running"))


def test_refresh_does_not_replace_coordinator_or_active_backend(tmp_db, monkeypatch):
    from types import SimpleNamespace
    from strides_ai.api import deps

    entered, finish = threading.Event(), threading.Event()
    config = {"label": "old"}

    def build(app, mode):
        backend = FakeBackend(entered, finish)
        backend.label = config["label"]
        backend.mode = mode
        return backend

    monkeypatch.setattr(deps, "build_backend", build)
    app = SimpleNamespace(state=SimpleNamespace())
    deps.init_backend(app, mode="cycling", provider="claude")
    coordinator = app.state.conversations
    turn = coordinator.acquire("running")
    coordinator.start(turn, "running profile", "hi", "hi", None)
    assert entered.wait(2)
    config["label"] = "new"
    deps.init_backend(app, mode="lifting", provider="openai")
    deps.init_backend(app)  # profile/sync refresh
    assert app.state.conversations is coordinator
    assert turn.backend.mode == "running"
    assert turn.backend.label == "old"
    finish.set()
    turn.worker.join(3)
    next_turn = coordinator.acquire("running")
    assert next_turn.backend.label == "new"
    coordinator.release(next_turn)


def test_stream_close_does_not_cancel_and_turn_completes(tmp_db):
    import asyncio
    from strides_ai.api.routers.chat import _sse_event_stream
    from strides_ai.db import chat_turns
    from sqlmodel import Session

    entered, finish = threading.Event(), threading.Event()

    class Backend:
        label = "fake"

        def stream_turn(self, system, message, on_token, attachments=None):
            on_token("first")
            entered.set()
            assert finish.wait(3)
            on_token(" second")
            return "first second", [("fact", "likes hills")], []

    coordinator = ConversationCoordinator(lambda mode: Backend())
    turn = coordinator.acquire("running")
    coordinator.start(turn, "prompt", "hello", "hello", None)
    assert entered.wait(2)

    async def disconnect():
        stream = _sse_event_stream(turn.tokens, None)
        assert await anext(stream) == "data: first\n\n"
        await stream.aclose()

    asyncio.run(disconnect())
    assert not turn.cancel.is_set()
    finish.set()
    turn.worker.join(3)
    assert db.get_recent_messages(mode="running")[-1]["content"] == "first second"
    with Session(db.get_engine()) as session:
        row = chat_turns.latest(session, "running")
        info = chat_turns.to_dict(row)
    assert info["status"] == "done" and not info["delivered"]
    assert info["events"]["memories"] == [{"category": "fact", "content": "likes hills"}]
    assert info["assistant_message_id"] is not None


def test_explicit_cancel_keeps_partial_text(tmp_db):
    entered = threading.Event()

    class Backend:
        label = "fake"

        def stream_turn(self, system, message, on_token, attachments=None):
            on_token("partial")
            entered.set()
            assert self.cancel_event.wait(3)
            on_token("more")

    coordinator = ConversationCoordinator(lambda mode: Backend())
    turn = coordinator.acquire("running")
    coordinator.start(turn, "prompt", "hello", "hello", None)
    assert entered.wait(2)
    assert coordinator.cancel("running") is True
    turn.worker.join(3)
    assert db.get_recent_messages(mode="running")[-1]["content"] == f"partial\n\n{INTERRUPTED}"
    assert coordinator.cancel("running") is False


def test_startup_recovery_marks_running_turns_interrupted(tmp_db):
    from sqlmodel import Session
    from strides_ai.api.conversations import recover_interrupted_turns
    from strides_ai.db import chat_turns

    with Session(db.get_engine()) as session:
        turn_id = chat_turns.create(session, "running", None)
        chat_turns.update(session, turn_id, partial_text="half a reply")
    recover_interrupted_turns()
    with Session(db.get_engine()) as session:
        assert chat_turns.to_dict(chat_turns.latest(session, "running"))["status"] == "interrupted"
    assert db.get_recent_messages(mode="running")[-1]["content"] == f"half a reply\n\n{INTERRUPTED}"


def test_active_endpoint_returns_finished_turn_once(tmp_db):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from strides_ai.api.routers import chat

    app = FastAPI()
    app.include_router(chat.router, prefix="/api")
    app.state.conversations = ConversationCoordinator(
        lambda mode: FakeBackend(*(threading.Event() for _ in range(2)))
    )
    client = TestClient(app)
    assert client.get("/api/chat/active?mode=running").json() == {"turn": None}

    entered, finish = threading.Event(), threading.Event()
    finish.set()
    coordinator = ConversationCoordinator(lambda mode: FakeBackend(entered, finish))
    turn = coordinator.acquire("running")
    coordinator.start(turn, "p", "hi", "hi", None)
    turn.worker.join(3)
    first = client.get("/api/chat/active?mode=running").json()["turn"]
    assert first["status"] == "done" and first["events"]["model"] == "captured-model"
    assert client.get("/api/chat/active?mode=running").json() == {"turn": None}


def test_pending_modes_lists_running_and_unseen_turns(tmp_db):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from strides_ai.api.routers import chat

    entered, finish = threading.Event(), threading.Event()
    coordinator = ConversationCoordinator(lambda mode: FakeBackend(entered, finish))
    app = FastAPI()
    app.include_router(chat.router, prefix="/api")
    app.state.conversations = coordinator
    client = TestClient(app)
    assert client.get("/api/chat/pending").json() == {"modes": []}

    turn = coordinator.acquire("cycling")
    coordinator.start(turn, "p", "hi", "hi", None)
    assert entered.wait(2)
    assert client.get("/api/chat/pending").json() == {"modes": ["cycling"]}
    finish.set()
    turn.worker.join(3)
    assert client.get("/api/chat/pending").json() == {"modes": ["cycling"]}  # done, not yet seen
    client.get("/api/chat/active?mode=cycling")  # reading it marks it delivered
    assert client.get("/api/chat/pending").json() == {"modes": []}
