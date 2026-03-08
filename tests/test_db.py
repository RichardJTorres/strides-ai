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
    assert msgs[0]["role"] == "user"
    assert msgs[0]["content"] == "Hello coach"
    assert msgs[1]["role"] == "assistant"
    assert msgs[1]["content"] == "Hello athlete"


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


# ── get_activities_for_mode ───────────────────────────────────────────────────


def test_get_activities_for_mode_running(tmp_db, sample_activity, sample_cycling_activity):
    db.upsert_activity(sample_activity)
    db.upsert_activity(sample_cycling_activity)
    rows = db.get_activities_for_mode("running")
    assert len(rows) == 1
    assert rows[0]["name"] == "Morning Run"


def test_get_activities_for_mode_cycling(tmp_db, sample_activity, sample_cycling_activity):
    db.upsert_activity(sample_activity)
    db.upsert_activity(sample_cycling_activity)
    rows = db.get_activities_for_mode("cycling")
    assert len(rows) == 1
    assert rows[0]["name"] == "Morning Ride"


def test_get_activities_for_mode_hybrid(tmp_db, sample_activity, sample_cycling_activity):
    db.upsert_activity(sample_activity)
    db.upsert_activity(sample_cycling_activity)
    rows = db.get_activities_for_mode("hybrid")
    assert len(rows) == 2


def test_get_activities_for_mode_empty(tmp_db):
    assert db.get_activities_for_mode("running") == []


# ── cycling cadence not doubled ───────────────────────────────────────────────


def test_upsert_does_not_double_cycling_cadence(tmp_db, sample_cycling_activity):
    db.upsert_activity(sample_cycling_activity)
    row = db.get_all_activities()[0]
    assert row["avg_cadence"] == pytest.approx(85.0)


# ── get_setting / set_setting ─────────────────────────────────────────────────


def test_get_setting_default(tmp_db):
    assert db.get_setting("mode", "running") == "running"


def test_get_setting_missing_key_no_default(tmp_db):
    assert db.get_setting("nonexistent") is None


def test_set_and_get_setting(tmp_db):
    db.set_setting("mode", "cycling")
    assert db.get_setting("mode") == "cycling"


def test_set_setting_overwrites(tmp_db):
    db.set_setting("mode", "running")
    db.set_setting("mode", "hybrid")
    assert db.get_setting("mode") == "hybrid"


# ── get_profile_fields / save_profile_fields ──────────────────────────────────


def test_get_profile_fields_returns_none_when_not_saved(tmp_db):
    assert db.get_profile_fields("running") is None


def test_save_and_get_profile_fields(tmp_db):
    fields = {"personal": {"name": "Alice"}, "goals": "sub-3"}
    db.save_profile_fields("running", fields)
    result = db.get_profile_fields("running")
    assert result["personal"]["name"] == "Alice"
    assert result["goals"] == "sub-3"


def test_profile_fields_isolated_per_mode(tmp_db):
    db.save_profile_fields("running", {"personal": {"name": "Runner"}})
    db.save_profile_fields("cycling", {"personal": {"name": "Cyclist"}})
    assert db.get_profile_fields("running")["personal"]["name"] == "Runner"
    assert db.get_profile_fields("cycling")["personal"]["name"] == "Cyclist"


def test_save_profile_fields_replaces_existing(tmp_db):
    db.save_profile_fields("running", {"goals": "first"})
    db.save_profile_fields("running", {"goals": "updated"})
    assert db.get_profile_fields("running")["goals"] == "updated"


# ── mode-scoped conversation history ─────────────────────────────────────────


def test_save_message_mode_isolation(tmp_db):
    db.save_message("user", "running question", mode="running")
    db.save_message("user", "cycling question", mode="cycling")
    run_msgs = db.get_recent_messages(10, mode="running")
    cyc_msgs = db.get_recent_messages(10, mode="cycling")
    assert len(run_msgs) == 1
    assert run_msgs[0]["content"] == "running question"
    assert len(cyc_msgs) == 1
    assert cyc_msgs[0]["content"] == "cycling question"


# ── get_message_count ─────────────────────────────────────────────────────────


def test_get_message_count_empty(tmp_db):
    assert db.get_message_count() == 0


def test_get_message_count_total(tmp_db):
    db.save_message("user", "msg1", mode="running")
    db.save_message("user", "msg2", mode="cycling")
    assert db.get_message_count() == 2


def test_get_message_count_filtered_by_mode(tmp_db):
    db.save_message("user", "run msg", mode="running")
    db.save_message("user", "ride msg", mode="cycling")
    assert db.get_message_count(mode="running") == 1
    assert db.get_message_count(mode="cycling") == 1


# ── get_messages_before ───────────────────────────────────────────────────────


def test_get_messages_before_returns_older(tmp_db):
    for i in range(5):
        db.save_message("user", f"msg {i}")
    all_msgs = db.get_recent_messages(10)
    pivot_id = all_msgs[3]["id"]
    older = db.get_messages_before(pivot_id, limit=10)
    assert all(m["id"] < pivot_id for m in older)


def test_get_messages_before_chronological_order(tmp_db):
    for i in range(5):
        db.save_message("user", f"msg {i}")
    all_msgs = db.get_recent_messages(10)
    last_id = all_msgs[-1]["id"]
    older = db.get_messages_before(last_id, limit=10)
    ids = [m["id"] for m in older]
    assert ids == sorted(ids)


def test_get_messages_before_respects_limit(tmp_db):
    for i in range(10):
        db.save_message("user", f"msg {i}")
    all_msgs = db.get_recent_messages(10)
    last_id = all_msgs[-1]["id"]
    older = db.get_messages_before(last_id, limit=3)
    assert len(older) <= 3


def test_get_messages_before_mode_filter(tmp_db):
    db.save_message("user", "run msg 1", mode="running")
    db.save_message("user", "ride msg 1", mode="cycling")
    db.save_message("user", "run msg 2", mode="running")
    all_msgs = db.get_recent_messages(10)
    beyond_all = all_msgs[-1]["id"] + 1
    older = db.get_messages_before(beyond_all, limit=10, mode="running")
    assert all("run" in m["content"] for m in older)
    assert len(older) == 2


# ── search_messages ───────────────────────────────────────────────────────────


def test_search_messages_finds_match(tmp_db):
    db.save_message("user", "What is my 5K pace?")
    db.save_message("assistant", "Your 5K pace is 4:30/km")
    results = db.search_messages("5K")
    assert len(results) == 2


def test_search_messages_case_insensitive(tmp_db):
    db.save_message("user", "tell me about my marathon")
    results = db.search_messages("MARATHON")
    assert len(results) == 1


def test_search_messages_no_match(tmp_db):
    db.save_message("user", "How was my long run?")
    assert db.search_messages("cycling") == []


def test_search_messages_mode_filter(tmp_db):
    db.save_message("user", "running pace question", mode="running")
    db.save_message("user", "cycling pace question", mode="cycling")
    results = db.search_messages("pace", mode="running")
    assert len(results) == 1
    assert "running" in results[0]["content"]


def test_search_messages_respects_limit(tmp_db):
    for i in range(10):
        db.save_message("user", f"pace question {i}")
    results = db.search_messages("pace", limit=3)
    assert len(results) == 3


# ── model column ──────────────────────────────────────────────────────────────


def test_save_message_stores_model(tmp_db):
    db.save_message("assistant", "Here is your plan", model="claude-sonnet-4-6")
    msgs = db.get_recent_messages(10)
    assert msgs[0]["model"] == "claude-sonnet-4-6"


def test_save_message_model_defaults_to_none(tmp_db):
    db.save_message("user", "Hello coach")
    msgs = db.get_recent_messages(10)
    assert msgs[0]["model"] is None


def test_get_recent_messages_includes_model_field(tmp_db):
    db.save_message("assistant", "reply", model="gemini:gemini-2.0-flash")
    msg = db.get_recent_messages(1)[0]
    assert "model" in msg


def test_migrate_backfills_claude_for_existing_rows(tmp_db):
    """Rows inserted before the model column existed should be backfilled with 'claude'."""
    import sqlite3 as _sqlite3

    # Insert a row bypassing the model column (simulates pre-migration data)
    with _sqlite3.connect(db.DB_PATH) as conn:
        conn.execute(
            "INSERT INTO conversations (role, content, mode) VALUES (?, ?, ?)",
            ("assistant", "old message", "running"),
        )

    # Re-run the migration (idempotent — column already exists, but backfill still applies)
    with _sqlite3.connect(db.DB_PATH) as conn:
        conn.row_factory = _sqlite3.Row
        db._migrate_conversations_model(conn)

    msgs = db.get_recent_messages(10)
    old = next(m for m in msgs if m["content"] == "old message")
    assert old["model"] == "claude"
