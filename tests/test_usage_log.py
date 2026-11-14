"""LLM usage log: pricing, recording (chat turns and one-shot analyses), summary and migration."""

import sqlite3
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from alembic import command
from sqlmodel import Session

from strides_ai.backends.pricing import cost, price_for
from strides_ai.db import engine as db_engine
from strides_ai.db import usage as usage_log
from strides_ai.db.engine import get_engine
from tests.test_backends import _claude_stream

# ── Pricing ─────────────────────────────────────────────────────────────────


def test_cost_splits_cached_and_fresh_input():
    usage = {"input_total": 1_000_000, "cache_read": 600_000, "cache_write": 100_000}
    usage["output_total"] = 500_000
    # opus-5-5: $4 in, $20 out, $0.20 cache read; cache write defaults to 1.25 x input.
    expected = 300_000 * 4 + 600_000 * 0.20 + 100_000 * 5 + 500_000 * 20
    assert cost("claude", "claude-opus-5-5", usage) == expected / 1e6


def test_longest_prefix_wins():
    assert price_for("claude", "claude-opus-5-5").input == 4
    assert price_for("claude", "claude-opus-5").input == 5
    assert price_for("claude", "claude-sonnet-5-5-preview").read == 0.10


def test_older_opus_models_are_unpriced_not_mispriced():
    assert price_for("claude", "claude-opus-4-1") is None
    assert price_for("claude", "claude-opus-4-8").input == 5


def test_unknown_model_or_unreported_tokens_have_no_cost_not_zero():
    full = {"input_total": 10, "output_total": 10}
    assert cost("openai", "gpt-5", full) is None
    assert cost("claude", "claude-opus-5-5", {"input_total": 10, "output_total": None}) is None
    assert cost("claude", "claude-opus-5-5", {"input_total": None, "output_total": 5}) is None
    assert cost("ollama", "llama3", full) == 0


# ── Recording and summary ───────────────────────────────────────────────────


def _row(**kw):
    base = dict(source="chat", provider="claude", model="claude-opus-5-5")
    return {**base, **kw}


def test_sum_rounds_keeps_unreported_figures_none():
    rounds = [
        {"input_total": 10, "output_total": 5, "cache_read": None, "reasoning": None},
        {"input_total": 20, "output_total": None, "cache_read": None, "reasoning": 3},
    ]
    assert usage_log.sum_rounds(rounds) == {
        "input_total": 30,
        "cache_read": None,
        "cache_write": None,
        "output_total": 5,
        "reasoning": 3,
    }


def test_summarize_groups_by_day_model_and_source(tmp_db):
    with Session(get_engine()) as s:
        usage_log.record(s, **_row(input_total=1_000_000, output_total=100_000))
        usage_log.record(s, **_row(source="deep_dive", input_total=10, output_total=10))
        usage_log.record(
            s, **_row(provider="openai", model="gpt-5", input_total=50, output_total=5)
        )
        usage_log.record(s, **_row(input_total=None, output_total=None))  # nothing reported
        result = usage_log.summarize(s, 30)

    totals = result["totals"]
    assert totals["calls"] == 4
    assert totals["input_tokens"] == 1_000_060
    assert totals["unpriced_calls"] == 2  # the gpt-5 call and the unreported one
    assert totals["cost_usd"] > 0
    assert {m["model"] for m in result["by_model"]} == {"claude-opus-5-5", "gpt-5"}
    assert {m["source"]: m["calls"] for m in result["by_source"]} == {"chat": 3, "deep_dive": 1}
    assert len(result["by_day"]) == 1


def test_summarize_excludes_rows_older_than_the_window(tmp_db):
    with Session(get_engine()) as s:
        usage_log.record(s, **_row(input_total=1, output_total=1))
        later = datetime.now(timezone.utc) + timedelta(days=40)
        assert usage_log.summarize(s, 30, now=later)["totals"]["calls"] == 0
        assert usage_log.summarize(s, 90, now=later)["totals"]["calls"] == 1


def test_record_safely_never_raises(tmp_db, monkeypatch):
    monkeypatch.setattr(db_engine, "get_engine", lambda: (_ for _ in ()).throw(RuntimeError("x")))
    usage_log.record_safely(**_row())  # must not raise


# ── Recording from the backends and the coordinator ─────────────────────────


def test_stateless_turn_logs_usage_with_its_source(tmp_db, mocker):
    client = mocker.patch("strides_ai.backends.claude.anthropic.Anthropic").return_value
    stream = _claude_stream(["hi"])
    stream.get_final_message.return_value.usage = SimpleNamespace(
        input_tokens=100,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=400,
        output_tokens=50,
    )
    client.messages.stream.return_value = stream
    from strides_ai.backends.claude import ClaudeBackend

    backend = ClaudeBackend("key", [], model="claude-opus-5-5")
    assert backend.stateless_turn("sys", "q", lambda _: None, source="insights") == "hi"

    with Session(get_engine()) as s:
        summary = usage_log.summarize(s, 1)
    assert summary["by_source"][0]["source"] == "insights"
    assert summary["totals"]["input_tokens"] == 500  # cached + uncached
    assert summary["totals"]["output_tokens"] == 50
    assert summary["totals"]["cache_read_tokens"] == 400


def test_a_call_that_reports_no_usage_is_still_logged_as_unpriced(tmp_db):
    from strides_ai.backends.base import BaseBackend

    class Silent(BaseBackend):
        label = "claude-opus-5-5"
        supports_attachments = False

        def stream_turn(self, *a, **k): ...

        def _count_request(self, *a, **k):
            return 0

        def _stateless_turn(self, system, user_input, on_token):
            return "text", None  # the provider sent no usage

    assert (
        Silent.__new__(Silent).stateless_turn("s", "q", lambda _: None, source="insights") == "text"
    )
    with Session(get_engine()) as s:
        totals = usage_log.summarize(s, 1)["totals"]
    assert totals["calls"] == 1 and totals["unpriced_calls"] == 1


def test_a_failed_usage_write_does_not_cost_the_reply(tmp_db, mocker):
    client = mocker.patch("strides_ai.backends.claude.anthropic.Anthropic").return_value
    client.messages.stream.return_value = _claude_stream(["ok"])
    mocker.patch("strides_ai.db.usage.record", side_effect=RuntimeError("disk full"))
    from strides_ai.backends.claude import ClaudeBackend

    assert ClaudeBackend("key", []).stateless_turn("s", "q", lambda _: None) == "ok"


def test_record_usage_logs_a_chat_turn_once(tmp_db):
    from strides_ai.api.conversations import _record_usage

    rounds = [
        {"input_total": 100, "output_total": 10, "cache_read": 80, "cache_write": None},
        {"input_total": 120, "output_total": 20, "cache_read": 100, "cache_write": None},
    ]
    backend = SimpleNamespace(
        provider="claude",
        label="claude-sonnet-5-5",
        _budget=SimpleNamespace(record=SimpleNamespace(rounds=rounds)),
    )
    _record_usage(SimpleNamespace(backend=backend, mode="running", turn_id=7))
    _record_usage(
        SimpleNamespace(backend=SimpleNamespace(), mode="running", turn_id=8)
    )  # no rounds

    with Session(get_engine()) as s:
        totals = usage_log.summarize(s, 1)["totals"]
    assert totals["calls"] == 1
    assert totals["input_tokens"] == 220
    assert totals["output_tokens"] == 30


# ── API and migration ───────────────────────────────────────────────────────


def test_usage_endpoint_returns_the_summary_and_validates_days(tmp_db):
    from fastapi.testclient import TestClient

    from strides_ai.api.app import app

    with Session(get_engine()) as s:
        usage_log.record(s, **_row(input_total=10, output_total=5))
    client = TestClient(app)
    body = client.get("/api/usage?days=7").json()
    assert body["days"] == 7 and body["totals"]["calls"] == 1
    assert client.get("/api/usage?days=0").status_code == 422
    assert client.get("/api/usage?days=366").status_code == 422


def _tables(path):
    con = sqlite3.connect(path)
    try:
        return {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        con.close()


def test_migration_019_adds_and_removes_the_table(tmp_db):
    cfg = db_engine._make_alembic_config()
    assert "llm_usage" in _tables(tmp_db)
    db_engine.reset_engine()
    command.downgrade(cfg, "018")
    assert "llm_usage" not in _tables(tmp_db)
    command.upgrade(cfg, "head")
    assert "llm_usage" in _tables(tmp_db)
