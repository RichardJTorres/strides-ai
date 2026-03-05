"""Unit tests for strides_ai.db — uses a temp SQLite file via the tmp_db fixture."""

import pytest

from strides_ai import db


# ── init_db ───────────────────────────────────────────────────────────────────

def test_init_db_creates_db_file(tmp_db):
    assert tmp_db.exists()


def test_init_db_idempotent(tmp_db):
    # Calling init_db twice should not raise
    db.init_db()


# ── upsert_activity / get_all_activities ──────────────────────────────────────

def test_upsert_and_retrieve(tmp_db, sample_activity):
    db.upsert_activity(sample_activity)
    rows = db.get_all_activities()
    assert len(rows) == 1
    assert rows[0]["id"] == sample_activity["id"]
    assert rows[0]["name"] == sample_activity["name"]


def test_upsert_calculates_pace(tmp_db, sample_activity):
    # distance=10_000m, moving_time=3_600s → pace = 3600 / 10 = 360 s/km
    db.upsert_activity(sample_activity)
    row = db.get_all_activities()[0]
    assert row["avg_pace_s_per_km"] == pytest.approx(360.0)


def test_upsert_doubles_cadence(tmp_db, sample_activity):
    # average_cadence=87 (half-cadence) → stored as 174
    db.upsert_activity(sample_activity)
    row = db.get_all_activities()[0]
    assert row["avg_cadence"] == pytest.approx(174.0)


def test_upsert_zero_distance_gives_null_pace(tmp_db, sample_activity):
    sample_activity["distance"] = 0
    sample_activity["moving_time"] = 3600
    db.upsert_activity(sample_activity)
    row = db.get_all_activities()[0]
    assert row["avg_pace_s_per_km"] is None


def test_upsert_null_cadence_stays_null(tmp_db, sample_activity):
    sample_activity["average_cadence"] = None
    db.upsert_activity(sample_activity)
    row = db.get_all_activities()[0]
    assert row["avg_cadence"] is None


def test_upsert_replaces_existing(tmp_db, sample_activity):
    db.upsert_activity(sample_activity)
    sample_activity["name"] = "Updated Run"
    db.upsert_activity(sample_activity)
    rows = db.get_all_activities()
    assert len(rows) == 1
    assert rows[0]["name"] == "Updated Run"


def test_get_all_activities_ordered_newest_first(tmp_db, sample_activity):
    db.upsert_activity(sample_activity)
    act2 = dict(sample_activity, id=1002, start_date_local="2025-07-01T07:00:00Z")
    db.upsert_activity(act2)
    rows = db.get_all_activities()
    assert rows[0]["date"] >= rows[1]["date"]


def test_get_stored_ids(tmp_db, sample_activity):
    db.upsert_activity(sample_activity)
    ids = db.get_stored_ids()
    assert sample_activity["id"] in ids


def test_get_stored_ids_empty(tmp_db):
    assert db.get_stored_ids() == set()


# ── save_message / get_recent_messages ────────────────────────────────────────

def test_save_and_get_messages(tmp_db):
    db.save_message("user", "Hello coach")
    db.save_message("assistant", "Hello athlete")
    msgs = db.get_recent_messages(10)
    assert len(msgs) == 2
    assert msgs[0] == {"role": "user", "content": "Hello coach"}
    assert msgs[1] == {"role": "assistant", "content": "Hello athlete"}


def test_get_recent_messages_chronological_order(tmp_db):
    for i in range(5):
        db.save_message("user", f"msg {i}")
    msgs = db.get_recent_messages(5)
    contents = [m["content"] for m in msgs]
    assert contents == [f"msg {i}" for i in range(5)]


def test_get_recent_messages_respects_limit(tmp_db):
    for i in range(10):
        db.save_message("user", f"msg {i}")
    msgs = db.get_recent_messages(4)
    assert len(msgs) == 4
    # Should be the LAST 4 messages, in chronological order
    assert msgs[-1]["content"] == "msg 9"


def test_get_recent_messages_empty(tmp_db):
    assert db.get_recent_messages(10) == []


# ── save_memory / get_all_memories ────────────────────────────────────────────

def test_save_and_get_memories(tmp_db):
    db.save_memory("goal", "Sub-3 marathon")
    mems = db.get_all_memories()
    assert len(mems) == 1
    assert mems[0]["category"] == "goal"
    assert mems[0]["content"] == "Sub-3 marathon"


def test_save_memory_deduplication(tmp_db):
    db.save_memory("goal", "Sub-3 marathon")
    db.save_memory("goal", "Sub-3 marathon")  # duplicate
    mems = db.get_all_memories()
    assert len(mems) == 1


def test_save_memory_different_content_both_stored(tmp_db):
    db.save_memory("goal", "Sub-3 marathon")
    db.save_memory("goal", "BQ")
    mems = db.get_all_memories()
    assert len(mems) == 2


def test_save_memory_returns_status(tmp_db):
    result = db.save_memory("pref", "early morning runs")
    assert result == "Memory saved."


def test_get_all_memories_empty(tmp_db):
    assert db.get_all_memories() == []


def test_get_all_memories_has_expected_keys(tmp_db):
    db.save_memory("injury", "knee")
    mem = db.get_all_memories()[0]
    assert {"id", "category", "content", "created_at"} == set(mem.keys())
