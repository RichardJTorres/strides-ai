"""Calendar entries: kinds, multiple entries per day, write invariants, atomic change sets."""

import json
import sqlite3

import pytest
from sqlmodel import Session

from strides_ai import db
from strides_ai.db import calendar as crud
from strides_ai.db.engine import get_engine

DAY = "2026-10-10"


def _create(**data):
    with Session(get_engine()) as s:
        return crud.create_entry(s, {"date": DAY, **data})


def _workout(wtype="Easy Run", **kw):
    return _create(kind="workout", workout_type=wtype, **kw)


def _update(entry_id, **patch):
    with Session(get_engine()) as s:
        return crud.update_entry(s, entry_id, patch)


def test_a_day_can_hold_several_entries(tmp_db):
    _workout("Easy Run", distance_km=5)
    _create(kind="race", title="Fall 10K", sport="run")
    _create(kind="travel", title="Flight to Denver")
    kinds = [r["kind"] for r in db.get_training_plan(DAY, DAY)]
    assert kinds == ["workout", "race", "travel"]


def test_race_reads_as_its_legacy_type_and_feeds_prefs(tmp_db):
    _create(kind="race", title="Fall 10K", sport="run", goal_time_s=2700)
    row = db.get_training_plan()[0]
    assert row["workout_type"] == "Running Race" and row["description"] == "Fall 10K"
    assert db.get_calendar_prefs()["races"][0]["target_time"] == "45:00"


def test_one_scored_workout_per_sport_per_day(tmp_db):
    _workout("Easy Run")
    with pytest.raises(crud.EntryError, match="already has a scored run"):
        _workout("Tempo Run")
    _workout("Easy Ride")  # a different sport is fine
    _workout("Yoga")
    _workout("Yoga")  # unscored types are unlimited


def test_moving_into_an_occupied_sport_slot_is_rejected(tmp_db):
    _workout("Easy Run")
    other = _create(kind="workout", workout_type="Long Run", date="2026-10-11")
    with pytest.raises(crud.EntryError):
        _update(other["id"], date=DAY)


def test_kind_is_immutable_and_details_are_validated(tmp_db):
    entry = _workout()
    with pytest.raises(crud.EntryError, match="kind cannot change"):
        _update(entry["id"], kind="race")
    with pytest.raises(crud.EntryError):
        _create(kind="rest", distance_km=5)
    with pytest.raises(crud.EntryError):
        _create(kind="nonsense")
    with pytest.raises(crud.EntryError):
        _create(kind="workout", workout_type="Underwater Basketweaving")
    with pytest.raises(crud.EntryError):
        _create(kind="race", sport="swim")
    assert len(db.get_training_plan()) == 1  # nothing half-written


def test_patch_distinguishes_omitted_from_null(tmp_db):
    entry = _workout(distance_km=5, intensity="easy", route_url="https://ridewithgps.com/routes/1")
    after = _update(entry["id"], duration_min=40)  # distance, intensity, route untouched
    assert (after["distance_km"], after["intensity"], after["route_url"]) == (
        5,
        "easy",
        "https://ridewithgps.com/routes/1",
    )
    cleared = _update(entry["id"], intensity=None)  # explicit null clears
    assert cleared["intensity"] is None and cleared["distance_km"] == 5


def test_structure_overrides_duration_and_is_dropped_for_runs(tmp_db):
    block = {"blocks": [{"kind": "steady", "duration_s": 1800, "pct": 0.8}]}
    ride = _workout("Indoor Ride", structure=block, duration_min=99)
    assert ride["duration_min"] == 30 and ride["structure_json"]
    run = _workout("Easy Run", structure=block)
    assert run["structure_json"] is None


def test_delete_removes_details_and_cascades(tmp_db):
    entry = _workout()
    race = _create(kind="race", title="R", sport="run")
    with Session(get_engine()) as s:
        crud.delete_entry(s, entry["id"])
    con = sqlite3.connect(db.DB_PATH)
    try:
        assert con.execute("select count(*) from workout_detail").fetchone()[0] == 0
        # With the foreign-key pragma on, deleting the parent row directly cascades.
        with get_engine().begin() as conn:
            conn.exec_driver_sql("DELETE FROM calendar_entry WHERE id = ?", (race["id"],))
        assert con.execute("select count(*) from race_detail").fetchone()[0] == 0
    finally:
        con.close()


def test_change_set_is_atomic(tmp_db):
    keep = _workout("Long Run")
    ops = [
        {"op": "delete", "id": keep["id"]},
        {"op": "create", "kind": "workout", "date": DAY, "workout_type": "Easy Ride"},
        {"op": "create", "kind": "race", "date": DAY, "sport": "swim"},  # invalid
    ]
    with Session(get_engine()) as s:
        with pytest.raises(crud.EntryError):
            crud.apply_changes(s, ops)
    plan = db.get_training_plan()
    assert [r["id"] for r in plan] == [keep["id"]]  # the delete was rolled back too


def test_change_set_replace_and_idempotent_retry(tmp_db):
    old = _workout("Long Run")
    ops = [
        {"op": "delete", "id": old["id"]},
        {"op": "create", "kind": "workout", "date": DAY, "workout_type": "Tempo Run"},
    ]
    first = db.apply_calendar_changes(ops, "req-1")
    again = db.apply_calendar_changes(ops, "req-1")  # a retry applies nothing new
    assert first == again and len(db.get_training_plan()) == 1
    assert db.get_training_plan()[0]["workout_type"] == "Tempo Run"


def test_stale_analysis_write_is_rejected(tmp_db):
    entry = _workout(distance_km=10)
    stale_hash = entry["inputs_hash"]
    _update(entry["id"], distance_km=12)  # inputs changed while the model was thinking
    with Session(get_engine()) as s:
        assert crud.save_workout_nutrition(s, entry["id"], {"x": 1}, stale_hash) is False
        fresh = crud.get_entry(s, entry["id"])["inputs_hash"]
        assert crud.save_workout_nutrition(s, entry["id"], {"x": 1}, fresh) is True
    assert json.loads(db.get_training_plan()[0]["nutrition_json"]) == {"x": 1}


def test_race_notes_keep_caches_but_distance_drops_them(tmp_db):
    race = _create(kind="race", title="R", sport="run", distance_km=10)
    with Session(get_engine()) as s:
        crud.save_workout_nutrition(s, race["id"], {"x": 1})
    _update(race["id"], notes="packet pickup at 3", priority="A")
    assert db.get_training_plan()[0]["nutrition_json"] is not None
    _update(race["id"], distance_km=21.1)
    assert db.get_training_plan()[0]["nutrition_json"] is None


def test_taxonomy_fixture_matches_kinds():
    """web/taxonomy.test.mjs asserts the same file against the frontend constants."""
    from pathlib import Path

    from strides_ai.kinds import taxonomy

    fixture = json.loads((Path(__file__).parent / "fixtures" / "taxonomy.json").read_text())
    t = taxonomy()
    assert fixture == {k: t[k] for k in fixture}
