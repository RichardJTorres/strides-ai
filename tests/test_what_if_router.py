"""POST /calendar/what-if: evaluates a hypothetical change against the calendar's own rules and
the saved plan, and never writes. Calls the handler directly (no TestClient), as the other router
tests do; the clock is the real one, so activities are seeded relative to today."""

from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlmodel import Session

from strides_ai import db
from strides_ai.api.routers.calendar import ChangeOp, WhatIfBody, what_if
from strides_ai.db import calendar as crud
from strides_ai.db.engine import get_engine
from strides_ai.units import UnitSystem
from tests.plan_helpers import save_planned_workout

TABLES = ("calendar_entry", "workout_detail", "race_detail", "change_request")
FUTURE = date.today() + timedelta(days=3)


def _request(mode="running"):
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(mode=mode)))


def _seed_history(weeks=8):
    """One-hour runs every second day, ending yesterday: enough history for load."""
    d, i = date.today() - timedelta(days=1), 1
    while d >= date.today() - timedelta(weeks=weeks):
        db.upsert_activity(
            {
                "id": i,
                "name": "Run",
                "start_date_local": f"{d.isoformat()}T07:00:00Z",
                "distance": 10_000.0,
                "moving_time": 3600,
                "elapsed_time": 3700,
                "total_elevation_gain": 50.0,
                "sport_type": "Run",
            }
        )
        d -= timedelta(days=2)
        i += 1


def _counts():
    with Session(get_engine()) as s:
        return {t: s.exec(text(f"select count(*) from {t}")).one()[0] for t in TABLES}


def _call(ops, mode="running"):
    body = WhatIfBody(ops=[ChangeOp(**o) for o in ops])
    with Session(get_engine()) as session:
        return what_if(body=body, request=_request(mode), session=session, units=UnitSystem.METRIC)


STRENGTH = {
    "op": "create",
    "kind": "workout",
    "date": FUTURE.isoformat(),
    "workout_type": "Strength",
    "duration_min": 45,
}


def test_returns_the_digest_and_writes_nothing(tmp_db):
    _seed_history()
    save_planned_workout(
        (FUTURE + timedelta(days=1)).isoformat(), "Easy Run", None, 5.0, None, 40, "easy"
    )
    before = _counts()
    out = _call([STRENGTH])
    assert _counts() == before
    assert db.get_training_plan(FUTURE.isoformat(), FUTURE.isoformat()) == []
    digest = out["digest"]
    change = digest["changes"][0]
    assert (change["counted"], change["hours"], change["label"]) == (True, 0.75, "Strength, 45 min")
    monday = FUTURE - timedelta(days=FUTURE.weekday())
    volume = next(m for m in digest["metrics"] if m["id"] == f"week.{monday.isoformat()}.volume")
    assert volume["delta"] == 0.75
    assert [n["hypothetical"] for n in digest["context"]["neighbors"] if n["type"]] == [True, False]


def test_a_change_the_calendar_would_refuse_is_refused_here_with_its_message(tmp_db):
    _seed_history()
    save_planned_workout(FUTURE.isoformat(), "Cross-Training", None, None, None, 30, "easy")
    before = _counts()
    with pytest.raises(HTTPException) as err:
        _call([STRENGTH])  # Strength and Cross-Training share one scored slot per day
    assert err.value.status_code == 400 and "already has a scored ambiguous" in err.value.detail
    with pytest.raises(HTTPException) as err:
        _call([{**STRENGTH, "workout_type": "Underwater Basketweaving"}])
    assert err.value.status_code == 400
    assert _counts() == before


def test_updating_an_unknown_entry_is_a_404_and_no_ops_is_a_400(tmp_db):
    _seed_history()
    with pytest.raises(HTTPException) as err:
        _call([{"op": "update", "id": 999, "duration_min": 30}])
    assert err.value.status_code == 404
    with pytest.raises(HTTPException) as err:
        _call([])
    assert err.value.status_code == 400


def test_deleting_an_unknown_entry_is_a_no_op_as_it_is_in_the_calendar(tmp_db):
    _seed_history()
    digest = _call([{"op": "delete", "id": 999}])["digest"]
    assert digest["changes"] == [] and digest["metrics"] == []


def test_lifting_is_evaluated_as_running_like_the_load_strip(tmp_db):
    _seed_history()
    assert _call([STRENGTH], mode="lifting")["digest"]["mode"] == "running"
    assert _call([STRENGTH], mode="cycling")["digest"]["mode"] == "cycling"


def test_what_if_then_apply_is_the_same_change(tmp_db):
    """The preview runs the very ops Apply sends, so applying them afterwards succeeds."""
    _seed_history()
    ops = [STRENGTH]
    _call(ops)
    with Session(get_engine()) as s:
        crud.apply_changes(s, [{**o, "op": "create"} for o in ops], "req-1")
    assert [
        r["workout_type"] for r in db.get_training_plan(FUTURE.isoformat(), FUTURE.isoformat())
    ] == ["Strength"]


# ── dry_run on the calendar writer ─────────────────────────────────────────────────


def test_dry_run_stores_nothing_and_does_not_remember_the_request_id(tmp_db):
    ops = [{"op": "create", "kind": "workout", "date": "2026-10-10", "workout_type": "Easy Run"}]
    with Session(get_engine()) as s:
        result = crud.apply_changes(s, ops, "same-id", dry_run=True)
    assert len(result["created"]) == 1  # provisional
    assert db.get_training_plan() == []
    assert _counts() == {t: 0 for t in TABLES}
    with Session(get_engine()) as s:  # the id was not consumed: a real apply with it still works
        crud.apply_changes(s, ops, "same-id")
    assert len(db.get_training_plan()) == 1


def test_dry_run_enforces_the_same_rules_as_a_write(tmp_db):
    save_planned_workout("2026-10-10", "Easy Run", None, 5.0, None, 30, "easy")
    clash = [{"op": "create", "kind": "workout", "date": "2026-10-10", "workout_type": "Tempo Run"}]
    with Session(get_engine()) as s:
        with pytest.raises(crud.EntryError, match="already has a scored run"):
            crud.apply_changes(s, clash, dry_run=True)
    assert len(db.get_training_plan()) == 1
