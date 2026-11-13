"""Mutation log, receipt and notice: what a turn changed is recorded with the change itself."""

import sqlite3

import pytest
from alembic import command
from sqlmodel import Session

from strides_ai import db
from strides_ai.api.conversations import ConversationCoordinator, recover_interrupted_turns
from strides_ai.coach import build_initial_history
from strides_ai.db import calendar, chat_turns, memories, mutations
from strides_ai.db import engine as db_engine
from strides_ai.db.calendar import EntryError
from strides_ai.turn_notice import receipt_text

RUN = {"op": "create", "kind": "workout", "date": "2026-11-20", "workout_type": "Easy Run"}


def _receipt(turn_id):
    with Session(db.get_engine()) as session:
        return mutations.build_receipt(session, turn_id)


def test_calendar_change_is_logged_with_the_change(tmp_db):
    with Session(db.get_engine()) as session:
        result = calendar.apply_changes(session, [RUN], turn_id=7)
    receipt = _receipt(7)
    assert receipt["committed"][0] == {
        "kind": "calendar",
        "created": [{"id": result["created"][0], "date": "2026-11-20", "label": "Easy Run"}],
        "updated": [],
        "deleted": [],
    }
    assert "Easy Run" in receipt_text(receipt) and f"[id {result['created'][0]}]" in receipt_text(
        receipt
    )


def test_failed_change_leaves_no_log_row(tmp_db):
    with Session(db.get_engine()) as session:
        with pytest.raises(EntryError):
            calendar.apply_changes(session, [RUN, {"op": "update", "id": None}], turn_id=8)
    assert _receipt(8) is None


def test_no_turn_id_writes_no_log(tmp_db):
    with Session(db.get_engine()) as session:
        calendar.apply_changes(session, [RUN])
        assert mutations.build_receipt(session, None) is None


def test_memory_saved_updated_and_duplicate(tmp_db):
    with Session(db.get_engine()) as session:
        assert memories.save(session, "goal", "Run Boston", turn_id=3) == "Memory saved."
        assert memories.save(session, "goal", "Run Boston", turn_id=3) == "Memory saved."
        memory_id = memories.get_all(session)[0].id
        memories.save(session, "goal", "Run Boston 2027", turn_id=3, memory_id=memory_id)
    items = _receipt(3)["committed"]
    assert [(m["action"], m["content"]) for m in items] == [
        ("saved", "Run Boston"),
        ("updated", "Run Boston 2027"),
    ]


def test_pending_proposal_is_listed_as_not_saved(tmp_db):
    db.log_mutation(
        4, "profile_proposal", "pending", {"label": "Goal", "op": "set", "proposed": "x"}
    )
    receipt = _receipt(4)
    assert receipt["committed"] == [] and receipt["pending"][0]["label"] == "Goal"
    text = receipt_text(receipt)
    assert "Not saved; waiting for you to accept" in text and "Saved:" not in text


class ChangingBackend:
    label = "m"
    turn_id = None

    def __init__(self, fail=True):
        self.fail = fail

    def stream_turn(self, system, message, on_token, attachments=None):
        on_token("Working on it. ")
        db.apply_calendar_changes([RUN], turn_id=self.turn_id)
        if self.fail:
            raise RuntimeError("provider failed")
        return "done", [], []


def test_provider_error_after_a_change_keeps_partial_text_and_receipt(tmp_db):
    coordinator = ConversationCoordinator(lambda mode: ChangingBackend())
    turn = coordinator.acquire("running")
    coordinator.start(turn, "p", "plan my week", "plan my week", None)
    turn.worker.join(3)
    reply = db.get_recent_messages(mode="running")[-1]
    assert reply["content"] == "Working on it. " and reply["notice"] == "failed"
    assert "Easy Run" in receipt_text(__import__("json").loads(reply["receipt_json"]))
    events = [str(c) for c in turn.tokens.queue]
    assert any(e.startswith("[NOTICE]") and "Easy Run" in e for e in events)


def test_startup_recovery_builds_the_receipt_from_the_log(tmp_db):
    with Session(db.get_engine()) as session:
        turn_id = chat_turns.create(session, "running", None)
        chat_turns.update(session, turn_id, partial_text="half")
        calendar.apply_changes(session, [RUN], turn_id=turn_id)
    recover_interrupted_turns()
    reply = db.get_recent_messages(mode="running")[-1]
    assert (reply["content"], reply["notice"]) == ("half", "interrupted")
    assert "Easy Run" in receipt_text(__import__("json").loads(reply["receipt_json"]))


def test_replay_adds_the_note_after_the_models_words_only_when_there_is_a_notice(tmp_db):
    receipt = '{"committed":[{"kind":"memory","action":"saved","category":"goal","content":"x"}],"pending":[]}'
    history = build_initial_history(
        [],
        [
            {"role": "assistant", "content": "ok", "notice": None, "receipt_json": receipt},
            {"role": "assistant", "content": "", "notice": "failed", "receipt_json": receipt},
            {"role": "assistant", "content": "half", "notice": "truncated", "receipt_json": None},
        ],
    )
    assert history[0]["content"] == "ok"
    assert (
        history[1]["content"].startswith("[App note: Chat failed")
        and "Memory saved [goal]: x" in history[1]["content"]
    )
    assert (
        history[2]["content"]
        == "half\n\n[App note: Response cut off at the length limit. Ask me to continue.]"
    )


def test_history_endpoint_returns_notice_and_receipt_text(tmp_db):
    from fastapi.testclient import TestClient

    from strides_ai.api.app import app

    with Session(db.get_engine()) as session:
        calendar.apply_changes(session, [RUN], turn_id=9)
        from strides_ai.db import conversations

        conversations.save(session, "assistant", "x", notice="failed", receipt=_receipt(9))
        conversations.save(session, "assistant", "y", receipt=_receipt(9))
    shown, quiet = TestClient(app).get("/api/history").json()["messages"]
    assert shown["notice_text"].startswith("Chat failed") and "Easy Run" in shown["receipt_text"]
    assert quiet["notice_text"] is None and quiet["receipt_text"] is None
    assert "receipt_json" not in shown


@pytest.fixture
def at_017(tmp_path, monkeypatch):
    db_file = tmp_path / "old.db"
    monkeypatch.setattr(db, "DB_PATH", db_file)
    monkeypatch.setattr(db_engine, "DB_PATH", db_file)
    db_engine.reset_engine()
    cfg = db_engine._make_alembic_config()
    command.upgrade(cfg, "017")
    return db_file, cfg


FAILED = "_Chat failed — resend your message to try again._"
INTERRUPTED = "_Chat interrupted — resend your message to generate a full response._"
STOPPED = "_Turn stopped: Input context limit reached. Earlier memory or calendar changes may already have completed._"
TRUNCATED = "_[Response truncated — hit the length limit. Ask me to continue.]_"


def test_migration_018_splits_notices_and_downgrades(at_017):
    db_file, cfg = at_017
    rows = [
        ("assistant", FAILED),
        ("assistant", f"partial\n\n{INTERRUPTED}"),
        ("assistant", f"Plan saved.\n\n{STOPPED}"),
        ("assistant", f"long\n\n{TRUNCATED}"),
        ("assistant", "A normal reply that mentions _Chat failed_ in passing."),
        ("user", FAILED),
    ]
    con = sqlite3.connect(db_file)
    con.executemany(
        "INSERT INTO conversations (role, content, mode) VALUES (?, ?, 'running')", rows
    )
    con.commit()
    con.close()
    command.upgrade(cfg, "018")
    con = sqlite3.connect(db_file)
    got = con.execute("SELECT content, notice FROM conversations ORDER BY id").fetchall()
    assert got == [
        ("", "failed"),
        ("partial", "interrupted"),
        ("Plan saved.", "limit"),
        ("long", "truncated"),
        ("A normal reply that mentions _Chat failed_ in passing.", None),
        (FAILED, None),  # a user message is never touched
    ]
    assert any((db_file.parent / "backups").glob("activities-pre-018-*.db"))
    con.close()
    command.downgrade(cfg, "017")
    con = sqlite3.connect(db_file)
    back = [r[0] for r in con.execute("SELECT content FROM conversations ORDER BY id")]
    assert (
        back[0] == FAILED
        and back[1] == f"partial\n\n{INTERRUPTED}"
        and back[3] == f"long\n\n{TRUNCATED}"
    )
    assert back[2].startswith("Plan saved.\n\n_Turn stopped:")
    assert not con.execute(
        "SELECT name FROM sqlite_master WHERE name='chat_turn_mutations'"
    ).fetchall()
    con.close()
