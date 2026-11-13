"""The replay harness, driven by a scripted fake provider. It never calls a real model."""

import sqlite3

import pytest

from strides_ai import db
from strides_ai.replay_chat import (
    REPLAY_PROMPTS,
    ReplayPrompt,
    copy_database,
    format_results,
    main,
    run_replay,
)
from tests.policy_helpers import make_backend

PLAN_CALL = (
    "update_training_plan",
    {"set": [{"date": "2026-12-01", "workout_type": "Easy Run", "distance": 5}]},
)


def fake_system(session, mode):
    return "mandatory"


def test_the_fixed_set_has_the_two_failing_prompts_in_order():
    ids = [p.id for p in REPLAY_PROMPTS]
    assert 8 <= len(ids) <= 10 and len(set(ids)) == len(ids)
    block, follow_up = REPLAY_PROMPTS[0], REPLAY_PROMPTS[1]
    assert "training block" in block.message and block.expect_writes is True
    assert follow_up.message == "Yes, let's do that."


def test_dry_run_lists_prompts_and_sends_nothing(capsys, monkeypatch):
    monkeypatch.setattr(
        "strides_ai.replay_chat.copy_database",
        lambda *a, **k: pytest.fail("a dry run must not copy or run anything"),
    )
    assert main([]) == 0
    out = capsys.readouterr().out
    assert "Dry run" in out and "--confirm-cost" in out and REPLAY_PROMPTS[0].message in out


def test_copy_leaves_the_source_alone(tmp_path):
    source = tmp_path / "real.db"
    conn = sqlite3.connect(source)
    conn.execute("create table t (x)")
    conn.execute("insert into t values (1)")
    conn.commit()
    conn.close()
    before = source.read_bytes()
    dest = copy_database(source, tmp_path)
    assert dest != source and dest.name == "activities.db"
    assert source.read_bytes() == before
    assert sqlite3.connect(dest).execute("select x from t").fetchall() == [(1,)]
    with pytest.raises(FileNotFoundError):
        copy_database(tmp_path / "missing.db", tmp_path)


def test_refuses_to_run_on_any_other_database(tmp_db, tmp_path):
    with pytest.raises(RuntimeError, match="refusing to run"):
        run_replay([], backend_factory=lambda mode: None, expected_db=tmp_path / "elsewhere.db")


def run(mocker, tmp_db, rounds_per_prompt, prompts, provider="claude"):
    scripts = iter(rounds_per_prompt)
    backends = []

    def factory(mode):
        backend, _ = make_backend(provider, mocker, next(scripts))
        backends.append(backend)
        return backend

    return run_replay(
        prompts, backend_factory=factory, expected_db=tmp_db, build_system=fake_system
    )


def test_a_complete_turn_with_valid_calendar_writes_is_ok(mocker, tmp_db):
    prompts = [ReplayPrompt("block", "running", "Schedule a block", expect_writes=True)]
    (result,) = run(mocker, tmp_db, [[{"calls": [PLAN_CALL]}, {"text": "Scheduled."}]], prompts)
    assert result.ok, result.problems
    assert result.complete and result.stop_reason == "complete" and result.status == "done"
    assert result.writes == {"created": 1, "updated": 0, "deleted": 0} and result.writes_valid
    assert [r["kind"] for r in result.rounds] == ["tool", "tool"]
    assert "Scheduled." in result.reply and isinstance(result.total_ms, int)
    assert "block" in format_results([result]) and "PROBLEM" not in format_results([result])


def test_a_prompt_that_hits_a_limit_is_flagged(mocker, tmp_db):
    prompts = [ReplayPrompt("block", "running", "Schedule a block", expect_writes=True)]
    (result,) = run(mocker, tmp_db, [[{"text": "partial", "cut_off": True}]], prompts)
    assert not result.ok
    assert result.stop_reason == "truncated"
    assert any("ended truncated" in p for p in result.problems)
    assert any("expected calendar changes" in p for p in result.problems)
    assert "PROBLEM" in format_results([result])


def test_unexpected_writes_and_followups_run_in_order(mocker, tmp_db):
    prompts = [
        ReplayPrompt("a", "running", "first", expect_writes=False),
        ReplayPrompt("b", "running", "Yes, let's do that."),
    ]
    first, second = run(
        mocker,
        tmp_db,
        [[{"calls": [PLAN_CALL]}, {"text": "done"}], [{"text": "ok"}]],
        prompts,
    )
    assert not first.ok and any("should not have" in p for p in first.problems)
    assert second.ok
    # The second turn saw the first exchange: it is in the stored conversation.
    contents = [m["content"] for m in db.get_recent_messages(mode="running")]
    assert contents[0] == "first" and contents[2] == "Yes, let's do that."


def test_a_rejected_message_is_reported_not_raised(mocker, tmp_db):
    prompts = [ReplayPrompt("big", "running", "x" * 600_000)]
    (result,) = run(mocker, tmp_db, [[{"text": "never sent"}]], prompts)
    assert result.status == "rejected" and not result.ok
