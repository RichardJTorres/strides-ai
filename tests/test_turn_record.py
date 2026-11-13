"""The per-turn record: what a chat turn sent, how long it took and why it stopped."""

import sqlite3

import pytest
from alembic import command
from fastapi import HTTPException
from sqlmodel import Session

from strides_ai import db
from strides_ai.api.conversations import ConversationCoordinator
from strides_ai.backends.base import BaseBackend
from strides_ai.budget import ContextPrompt, Limits, Reducible, Required
from strides_ai.db import chat_turns
from strides_ai.db import engine as db_engine
from strides_ai.turn_record import TurnRecord
from tests.test_backends import _claude_stream
from tests.test_budgets import adapter  # noqa: F401  (shared four-provider fixture)

# ── TurnRecord ────────────────────────────────────────────────────────────────


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


def test_record_tracks_rounds_tools_and_timings():
    clock = Clock()
    record = TurnRecord(model="m", limits=Limits(), clock=clock)
    record.start_round(1, 1200, "estimated")
    clock.now += 0.25
    record.first_text()
    clock.now += 0.25
    record.first_text()  # only the first text of a round counts
    record.tool()
    record.end_round(321, 300)
    record.start_round(2, 1500, "measured")
    clock.now += 1.0
    record.end_round(None, 40)  # provider reported nothing: only the app's estimate is kept

    result = record.to_dict(total_ms=4000)

    assert result["v"] == 1 and result["model"] == "m" and result["total_ms"] == 4000
    assert result["limits"]["tool_rounds"] == 5
    first, second = result["rounds"]
    assert first["n"] == 1 and first["est_input"] == 1200 and first["count_kind"] == "estimated"
    assert first["first_text_ms"] == 250 and first["duration_ms"] == 500
    assert first["output_total"] == 321 and first["output_est"] == 300
    assert first["tools_run"] == 1
    assert second["output_total"] is None and second["output_est"] == 40
    assert second["duration_ms"] == 1000
    assert second["first_text_ms"] is None
    assert result["stop"] == {"reason": "complete", "detail": None}


def test_retries_before_the_first_round_are_kept_for_it():
    record = TurnRecord()
    record.retry(1)
    record.retry(2)
    record.start_round(1, 10, "estimated")
    record.retry(4)
    record.start_round(2, 10, "estimated")

    first, second = record.to_dict()["rounds"]
    assert (first["retries"], first["retry_wait_ms"]) == (3, 7000)
    assert (second["retries"], second["retry_wait_ms"]) == (0, 0)


def test_record_methods_are_safe_before_any_round():
    record = TurnRecord()
    record.first_text()
    record.tool()
    record.end_round(5)
    record.set_stop("provider_error", "x" * 500)

    result = record.to_dict()
    assert result["rounds"] == [] and result["sections"] == [] and result["fixed"] is None
    assert len(result["stop"]["detail"]) == 300


# ── Section names ─────────────────────────────────────────────────────────────


def test_context_prompt_is_the_fullest_version_with_the_date_last():
    prompt = ContextPrompt(
        [
            Required("mandatory", "base", "base"),
            Required("profile", "profile", ""),
            Reducible("notes", 0.15, lambda k: "n" * k, full=3, join="\n"),
        ],
        tail="date",
    )
    assert [p.key for p in prompt.required] == ["mandatory", "profile"]
    assert [p.key for p in prompt.reducible] == ["notes"]
    assert str(prompt) == "base\nnnn\n\ndate"
    assert prompt.stable({"notes": 1}).startswith("base\nn")


# ── Admission ─────────────────────────────────────────────────────────────────


def test_admission_names_what_was_sent_and_what_was_left_out(mocker):
    mocker.patch("strides_ai.backends.claude.anthropic.Anthropic")
    from strides_ai.backends.claude import ClaudeBackend

    backend = ClaudeBackend("fake", [{"role": "user", "content": "orphan"}])
    prompt = ContextPrompt(
        [
            Required("mandatory", "base instructions", "base instructions"),
            Required("profile", "profile", "profile text"),
            Reducible("other_memories", 0.15, lambda k: "m" * 600_000, full=1, levels=(1, 0)),
            Required("upcoming_workouts", "workouts", "plan text"),
            Reducible("recent_activities", 0.25, lambda k: "one activity", full=1, levels=(1, 0)),
        ],
        tail="today",
    )

    backend.prepare_turn(prompt, "hello", None)

    admission = backend._admission
    levels = {s["key"]: s.get("level") for s in admission["sections"]}
    # The oversized section is cut alone; the sections after it are still sent.
    assert levels == {
        "mandatory": None,
        "profile": None,
        "upcoming_workouts": None,
        "other_memories": 0,
        "recent_activities": 1,
    }
    memories = next(s for s in admission["sections"] if s["key"] == "other_memories")
    assert memories["bytes"] == 0 and memories["full_est"] > 200_000
    assert all(type(value) is int for value in admission["fixed"].values())
    assert admission["history"]["messages"] == 0 and admission["history"]["dropped"] == 1
    assert admission["ladder"] == [] and type(admission["required_est"]) is int
    assert type(admission["admission_ms"]) is int and admission["est_input"] > 0
    assert admission["count_kind"] == "estimated"


# ── Stored with the turn ──────────────────────────────────────────────────────


def _strings(value):
    """Every string value stored anywhere in a record (keys excluded)."""
    if isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)
    elif isinstance(value, str):
        yield value


def _run_turn(backend, message="hello", system="mandatory"):
    coordinator = ConversationCoordinator(lambda _: backend)
    turn = coordinator.acquire("running")
    coordinator.start(turn, system, message, message, None)
    turn.worker.join(5)
    assert not turn.worker.is_alive()
    with Session(db_engine.get_engine()) as session:
        row = session.get(chat_turns.ChatTurn, turn.turn_id)
        return turn.turn_id, row.status, chat_turns.budget(row)


def test_stopped_turn_stores_its_record(adapter, tmp_db, monkeypatch):  # noqa: F811
    monkeypatch.setattr(BaseBackend, "limits", property(lambda _: Limits(tool_rounds=1)))
    backend, _ = adapter()

    _, status, record = _run_turn(backend)

    assert status == "done"
    assert record["model"] == backend.label
    assert record["stop"]["reason"] == "round_limit"
    assert [r["kind"] for r in record["rounds"]] == ["tool", "reply"]
    assert record["rounds"][0]["tools_run"] == 1 and record["rounds"][1]["tools_run"] == 0
    assert type(record["rounds"][0]["duration_ms"]) is int
    assert type(record["total_ms"]) is int and type(record["admission_ms"]) is int
    assert record["fixed"]["mandatory"] > 0 and record["limits"]["tool_rounds"] == 1


def test_completed_turn_stores_its_record(mocker, tmp_db):
    client = mocker.patch("strides_ai.backends.claude.anthropic.Anthropic").return_value
    client.messages.stream.return_value = _claude_stream(["Hello", " world"])
    from strides_ai.backends.claude import ClaudeBackend

    _, status, record = _run_turn(
        ClaudeBackend("fake", []), message="secret question", system="secret system prompt"
    )

    assert status == "done"
    assert record["stop"] == {"reason": "complete", "detail": None}
    (only,) = record["rounds"]
    assert only["n"] == 1 and only["tools_run"] == 0
    assert type(only["first_text_ms"]) is int
    # The mocked provider reports no usage, so only the app's estimate is recorded.
    assert only["output_total"] is None and type(only["output_est"]) is int
    # Neither the reply, the message nor the system prompt enters the record.
    stored = str(record).lower()
    assert "hello" not in stored and "secret question" not in stored
    assert "secret system prompt" not in stored


def test_failed_turn_stores_its_record(mocker, tmp_db):
    client = mocker.patch("strides_ai.backends.claude.anthropic.Anthropic").return_value
    client.messages.stream.side_effect = RuntimeError("provider exploded")
    from strides_ai.backends.claude import ClaudeBackend

    _, status, record = _run_turn(ClaudeBackend("fake", []))

    assert status == "failed"
    # Provider error text can echo the request, so only the error class is stored.
    assert record["stop"] == {"reason": "provider_error", "detail": "RuntimeError"}
    assert len(record["rounds"]) == 1 and record["rounds"][0]["output_total"] is None


def test_reused_backend_does_not_carry_an_earlier_record(mocker, tmp_db):
    client = mocker.patch("strides_ai.backends.claude.anthropic.Anthropic").return_value
    client.messages.stream.return_value = _claude_stream(["first"])
    from strides_ai.backends.claude import ClaudeBackend

    backend = ClaudeBackend("fake", [])
    _run_turn(backend)
    assert backend._budget is not None

    backend.prepare_turn("mandatory", "second", None)

    assert backend._budget is None and backend._admission["fixed"]["mandatory"] > 0


def test_backend_without_a_budget_stores_no_record(tmp_db):
    class Plain:
        label = "plain"

        def stream_turn(self, system, message, on_token, attachments=None):
            on_token("hi")
            return "hi", [], []

    _, status, record = _run_turn(Plain())
    assert status == "done" and record is None


# ── Endpoint ──────────────────────────────────────────────────────────────────


def test_budget_endpoint_returns_the_record_or_404(mocker, tmp_db):
    from strides_ai.api.routers.chat import turn_budget

    client = mocker.patch("strides_ai.backends.claude.anthropic.Anthropic").return_value
    client.messages.stream.return_value = _claude_stream(["ok"])
    from strides_ai.backends.claude import ClaudeBackend

    turn_id, _, record = _run_turn(ClaudeBackend("fake", []))

    with Session(db_engine.get_engine()) as session:
        body = turn_budget(turn_id, session)
        assert body == {"turn_id": turn_id, "mode": "running", "status": "done", "budget": record}
        with pytest.raises(HTTPException) as exc:
            turn_budget(turn_id + 99, session)
    assert exc.value.status_code == 404


def test_active_turn_payload_does_not_carry_the_record(mocker, tmp_db):
    client = mocker.patch("strides_ai.backends.claude.anthropic.Anthropic").return_value
    client.messages.stream.return_value = _claude_stream(["ok"])
    from strides_ai.backends.claude import ClaudeBackend

    turn_id, _, _ = _run_turn(ClaudeBackend("fake", []))
    with Session(db_engine.get_engine()) as session:
        payload = chat_turns.to_dict(session.get(chat_turns.ChatTurn, turn_id))
    assert "budget" not in payload and "budget_json" not in payload


# ── Report ────────────────────────────────────────────────────────────────────


def _row_counts(db_file):
    con = sqlite3.connect(db_file)
    try:
        return {
            table: con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("conversations", "chat_turns", "memories", "settings")
        }
    finally:
        con.close()


def test_context_report_runs_offline_and_changes_nothing(mocker, tmp_db):
    from strides_ai.config import Settings
    from strides_ai.context_report import build_report, format_report

    client = mocker.patch("strides_ai.backends.claude.anthropic.Anthropic").return_value
    mocker.patch(
        "strides_ai.api.deps.get_settings",
        return_value=Settings(provider="claude", anthropic_api_key="k"),
    )
    db.save_memory("goal", "run a marathon")
    before = _row_counts(tmp_db)

    report = build_report("running")
    text = format_report(report)

    client.messages.count_tokens.assert_not_called()
    client.messages.stream.assert_not_called()
    assert report["rejected"] is None and report["measured"] is False
    assert {"protected_memories", "other_memories"} <= {s["key"] for s in report["sections"]}
    assert "mandatory" in text and "other_memories" in text and "Request as sent" in text
    assert "Ladder steps applied" in text and "Required context" in text
    # The memory text itself is never printed.
    assert "marathon" not in text
    assert _row_counts(tmp_db) == before


# ── Migration ─────────────────────────────────────────────────────────────────


def _chat_turn_columns(db_file):
    con = sqlite3.connect(db_file)
    try:
        return [row[1] for row in con.execute("PRAGMA table_info(chat_turns)")]
    finally:
        con.close()


def test_migration_017_adds_and_removes_the_column(tmp_db):
    cfg = db_engine._make_alembic_config()
    assert "budget_json" in _chat_turn_columns(tmp_db)

    con = sqlite3.connect(tmp_db)
    con.execute("INSERT INTO chat_turns (mode, status) VALUES ('running', 'done')")
    con.commit()
    con.close()

    db_engine.reset_engine()
    command.downgrade(cfg, "016")
    assert "budget_json" not in _chat_turn_columns(tmp_db)
    command.upgrade(cfg, "head")
    assert "budget_json" in _chat_turn_columns(tmp_db)

    con = sqlite3.connect(tmp_db)
    rows = con.execute("SELECT mode, status, budget_json FROM chat_turns").fetchall()
    con.close()
    # The existing turn survives both directions and simply has no record.
    assert rows == [("running", "done", None)]
