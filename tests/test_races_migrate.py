"""Legacy calendar_prefs.races -> planned race workouts (alembic 014)."""

import json

import sqlalchemy as sa

from strides_ai import db
from strides_ai.db.engine import get_engine
from strides_ai.races_migrate import migrate_races


def _set_races(conn, races, raw=None):
    conn.execute(sa.text("DELETE FROM calendar_prefs"))
    conn.execute(
        sa.text("INSERT INTO calendar_prefs (id, blocked_days, races) VALUES (1, '[]', :r)"),
        {"r": raw if raw is not None else json.dumps(races)},
    )


def _plan(conn):
    rows = conn.execute(
        sa.text("SELECT date, workout_type, description FROM training_plan ORDER BY date")
    )
    return [tuple(r) for r in rows]


def test_no_prefs_row_is_a_noop(tmp_db):
    with get_engine().begin() as conn:
        conn.execute(sa.text("DELETE FROM calendar_prefs"))
        migrate_races(conn)
        assert _plan(conn) == []


def test_empty_races(tmp_db):
    with get_engine().begin() as conn:
        _set_races(conn, [])
        migrate_races(conn)
        assert _plan(conn) == []


def test_populated_races_become_workouts_and_list_is_cleared(tmp_db):
    with get_engine().begin() as conn:
        _set_races(
            conn,
            [
                {"date": "2026-10-11", "name": "Chicago", "target_time": "3:30:00"},
                {"date": "2026-11-01"},
                {"name": "no date"},
            ],
        )
        migrate_races(conn)
        assert _plan(conn) == [
            ("2026-10-11", "Race", "Chicago (target 3:30:00)"),
            ("2026-11-01", "Race", "Race"),
        ]
        assert conn.execute(sa.text("SELECT races FROM calendar_prefs")).scalar() == "[]"
        migrate_races(conn)  # idempotent
        assert len(_plan(conn)) == 2
    assert [r["name"] for r in db.get_calendar_prefs()["races"]] == [
        "Chicago (target 3:30:00)",
        "Race",
    ]


def test_date_collision_keeps_existing_workout(tmp_db):
    db.save_planned_workout("2026-10-11", "Long Run", "Keep me", 20.0, None, None, "easy")
    with get_engine().begin() as conn:
        _set_races(conn, [{"date": "2026-10-11", "name": "Chicago"}])
        migrate_races(conn)
        assert _plan(conn) == [("2026-10-11", "Long Run", "Keep me")]


def test_malformed_json_is_tolerated(tmp_db):
    with get_engine().begin() as conn:
        _set_races(conn, None, raw="not json")
        migrate_races(conn)
        assert _plan(conn) == []
