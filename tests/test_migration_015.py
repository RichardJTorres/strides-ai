"""Migration 015: training_plan + calendar_prefs.races -> calendar entries, losslessly."""

import json
import sqlite3

import pytest
from alembic import command

from strides_ai import db
from strides_ai.db import engine as db_engine


@pytest.fixture
def at_013(tmp_path, monkeypatch):
    db_file = tmp_path / "old.db"
    monkeypatch.setattr(db, "DB_PATH", db_file)
    monkeypatch.setattr(db_engine, "DB_PATH", db_file)
    db_engine.reset_engine()
    cfg = db_engine._make_alembic_config()
    command.upgrade(cfg, "013")
    return db_file, cfg


def _seed(db_file, plan_rows, races_json):
    con = sqlite3.connect(db_file)
    for r in plan_rows:
        cols = ", ".join(r)
        marks = ", ".join("?" for _ in r)
        con.execute(f"INSERT INTO training_plan ({cols}) VALUES ({marks})", tuple(r.values()))
    con.execute("DELETE FROM calendar_prefs")
    con.execute("INSERT INTO calendar_prefs (id, races) VALUES (1, ?)", (races_json,))
    con.commit()
    con.close()


def _entries(db_file):
    con = sqlite3.connect(db_file)
    con.row_factory = sqlite3.Row
    rows = [dict(r) for r in con.execute("SELECT * FROM calendar_entry ORDER BY date, id")]
    con.close()
    return rows


def test_every_mapping_rule(at_013):
    db_file, cfg = at_013
    plan = [
        {
            "date": "2026-10-01",
            "workout_type": "Long Ride",
            "description": "Steady",
            "distance_km": 80.0,
            "intensity": "easy",
            "nutrition_json": '{"x":1}',
            "route_analysis_json": '{"verdict":"fits"}',
            "structure_json": None,
            "created_at": "2026-09-01 10:00:00",
        },
        {"date": "2026-10-02", "workout_type": "Rest", "description": "Sleep in"},
        {"date": "2026-10-03", "workout_type": "Easy Run", "intensity": "rest"},  # legacy rest
        {"date": "2026-10-10", "workout_type": "Running Race", "description": "Fall Half"},
        {"date": "2026-10-11", "workout_type": "Race", "description": None},
    ]
    races = [
        {"date": "2026-10-10", "name": "fall half", "target_time": "1:45:00"},  # duplicate
        {"date": "2026-10-11", "name": "Gravel Grinder", "target_time": "sub 4"},  # generic plan
        {"date": "2026-12-01", "name": "Turkey Trot", "target_time": "30:00"},
        {"date": "2026-10-10", "name": "Charity 5K", "target_time": ""},  # same day, other race
        {"date": "not-a-date", "name": "Broken"},  # malformed -> skipped
    ]
    _seed(db_file, plan, json.dumps(races))
    command.upgrade(cfg, "head")

    rows = _entries(db_file)
    by_key = {(r["date"], r["title"] or r["notes"]): r for r in rows}
    assert by_key[("2026-10-01", None)]["created_at"] == "2026-09-01 10:00:00"
    assert by_key[("2026-10-02", "Sleep in")]["kind"] == "rest"
    assert {r["kind"] for r in rows if r["date"] == "2026-10-03"} == {"rest"}

    halves = [r for r in rows if r["date"] == "2026-10-10"]
    assert sorted(r["title"] for r in halves) == ["Charity 5K", "Fall Half"]  # merged, not dropped

    con = sqlite3.connect(db_file)
    con.row_factory = sqlite3.Row
    half = next(r for r in halves if r["title"] == "Fall Half")
    detail = con.execute("SELECT * FROM race_detail WHERE entry_id=?", (half["id"],)).fetchone()
    assert detail["goal_time_s"] == 6300 and detail["sport"] == "run"
    gravel = next(r for r in rows if r["title"] == "Gravel Grinder")
    g = con.execute("SELECT * FROM race_detail WHERE entry_id=?", (gravel["id"],)).fetchone()
    assert g["goal_text"] == "sub 4" and g["goal_time_s"] is None
    ride = con.execute("SELECT * FROM workout_detail WHERE objective='Steady'").fetchone()
    assert ride["nutrition_json"] == '{"x":1}' and ride["route_analysis_json"]
    assert not any(r["date"] == "not-a-date" for r in rows)
    # The originals stay recoverable.
    assert con.execute("SELECT count(*) FROM training_plan_legacy").fetchone()[0] == 5
    assert "Broken" in con.execute("SELECT races_legacy FROM calendar_prefs").fetchone()[0]
    assert con.execute("SELECT races FROM calendar_prefs").fetchone()[0] == "[]"
    con.close()
    assert list((db_file.parent / "backups").glob("activities-pre-015-*.db"))


def test_long_race_descriptions_become_a_short_name_plus_notes(at_013):
    db_file, cfg = at_013
    long = "Evergreen Grinder — 58.97mi, steep terrain. Pace conservatively early and fuel often."
    _seed(db_file, [{"date": "2026-12-12", "workout_type": "Race", "description": long}], "[]")
    command.upgrade(cfg, "head")
    (race,) = _entries(db_file)
    assert race["title"] == "Evergreen Grinder" and race["notes"] == long


def test_empty_database_needs_no_backup(at_013):
    db_file, cfg = at_013
    command.upgrade(cfg, "head")
    assert not (db_file.parent / "backups").exists()


def test_malformed_prefs_json_does_not_abort(at_013):
    db_file, cfg = at_013
    _seed(db_file, [], "{not json")
    command.upgrade(cfg, "head")
    assert _entries(db_file) == []


def test_downgrade_restores_the_old_table(at_013):
    db_file, cfg = at_013
    _seed(db_file, [{"date": "2026-10-01", "workout_type": "Easy Run"}], "[]")
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "013")
    con = sqlite3.connect(db_file)
    assert con.execute("SELECT workout_type FROM training_plan").fetchone()[0] == "Easy Run"
    con.close()
