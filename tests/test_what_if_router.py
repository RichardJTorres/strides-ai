"""POST /calendar/what-if: evaluates a hypothetical change against the calendar's own rules and
the saved plan, and never writes. Calls the handler directly (no TestClient), as the other router
tests do; the clock is the real one, so activities are seeded relative to today."""

import asyncio
import json
from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlmodel import Session

from strides_ai import db
from strides_ai.api.routers.calendar import (
    BulkBody,
    ChangeOp,
    WhatIfBody,
    bulk_calendar_entries,
    what_if,
)
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


class _StubBackend:
    label = "stub-model"

    def __init__(self, reply=None, error=None):
        self.reply, self.error, self.calls = reply, error, []

    def stateless_turn(self, system, user_input, on_token, source="other"):
        self.calls.append({"system": system, "user": user_input, "source": source})
        if self.error:
            raise self.error
        return self.reply


def _call(ops, mode="running", llm=False, backend=None, question=""):
    body = WhatIfBody(ops=[ChangeOp(**o) for o in ops], question=question)
    with Session(get_engine()) as session:
        return asyncio.run(
            what_if(
                body=body,
                request=_request(mode),
                llm=llm,
                session=session,
                backend=backend,
                units=UnitSystem.METRIC,
            )
        )


def _reply(**over):
    return json.dumps(
        {
            "verdict": "fine",
            "headline": "Fine.",
            "reasons": [{"text": "It adds 0.75 h.", "metric_ids": ["change.1"]}],
            "suggested": None,
            **over,
        }
    )


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


# ── the coach's verdict ─────────────────────────────────────────────────────────────


def test_without_llm_the_coach_is_never_called(tmp_db):
    _seed_history()
    backend = _StubBackend(_reply())
    out = _call([STRENGTH], llm=False, backend=backend)
    assert backend.calls == [] and out["coach"] is None and out["coach_error"] is None


def test_the_verdict_comes_back_with_the_digest_and_nothing_is_written(tmp_db):
    _seed_history()
    backend = _StubBackend(_reply())
    before = _counts()
    out = _call([STRENGTH], llm=True, backend=backend, question="Kettlebell on Friday?")
    assert _counts() == before
    coach = out["coach"]
    assert (coach["verdict"], coach["headline"], coach["model"]) == ("fine", "Fine.", "stub-model")
    assert coach["suggestion"] is None and coach["suggestion_rejected"] is None
    call = backend.calls[0]
    assert call["source"] == "what_if"  # usage is logged under it
    assert "Kettlebell on Friday?" in call["user"] and "[change.1]" in call["user"]


def test_a_blocked_day_cannot_be_called_fine(tmp_db):
    _seed_history()
    with Session(get_engine()) as s:
        crud.save_prefs(s, [FUTURE.isoformat()])
    out = _call([STRENGTH], llm=True, backend=_StubBackend(_reply(verdict="fine")))
    assert out["coach"]["verdict"] == "bad"


def test_protected_notes_reach_the_prompt_and_other_notes_do_not(tmp_db):
    _seed_history()
    db.save_memory("injury", "Left knee: no impact work")
    db.save_memory("preference", "Likes hummus")
    backend = _StubBackend(_reply())
    _call([STRENGTH], llm=True, backend=backend)
    assert "Left knee" in backend.calls[0]["user"] and "hummus" not in backend.calls[0]["user"]


def test_a_failing_coach_keeps_the_digest(tmp_db):
    _seed_history()
    out = _call([STRENGTH], llm=True, backend=_StubBackend(error=RuntimeError("provider down")))
    assert out["coach"] is None
    assert out["coach_error"] == "The coach could not be reached (RuntimeError)."
    assert "provider down" not in out["coach_error"]  # the provider's text stays in the log
    assert out["digest"]["changes"][0]["counted"] is True


def test_an_unreadable_reply_keeps_the_digest(tmp_db):
    _seed_history()
    out = _call([STRENGTH], llm=True, backend=_StubBackend("I think it is fine!"))
    assert out["coach"] is None and "could not be read" in out["coach_error"]
    assert out["digest"]["metrics"]


# ── the coach's suggestion is checked before it is offered ───────────────────────────


def _suggest(**suggested):
    return _call(
        [STRENGTH], llm=True, backend=_StubBackend(_reply(verdict="caution", suggested=suggested))
    )["coach"]


def test_a_valid_suggestion_is_offered_with_its_own_numbers_and_applies_atomically(tmp_db):
    _seed_history()
    later = (FUTURE + timedelta(days=2)).isoformat()
    coach = _suggest(set=[{"date": later, "workout_type": "Strength", "duration_min": 30}])
    suggestion = coach["suggestion"]
    assert coach["suggestion_rejected"] is None and suggestion["warnings"] == []
    assert [c["date"] for c in suggestion["changes"]] == [later]
    assert suggestion["metrics"], "the suggestion carries its own before/after numbers"
    assert db.get_training_plan(later, later) == []  # offered, not applied
    with Session(get_engine()) as s:  # the ops are exactly what the bulk endpoint takes
        bulk_calendar_entries(
            body=BulkBody(ops=[ChangeOp(**o) for o in suggestion["ops"]], request_id="r1"),
            session=s,
        )
    assert [r["workout_type"] for r in db.get_training_plan(later, later)] == ["Strength"]


@pytest.mark.parametrize(
    "suggested,why",
    [
        ({"set": [{"id": 999, "duration_min": 20}]}, "No calendar entry with id 999"),
        ({"set": [{"date": "2026-13-45", "workout_type": "Strength"}]}, ""),
        ({"set": [{"date": FUTURE.isoformat(), "workout_type": "Nonsense"}]}, ""),
        (
            {"set": [{"date": FUTURE.isoformat(), "workout_type": "Easy Run", "distance": 5}]},
            "distance_unit",
        ),
        ({"set": ["not an object"]}, "not an object"),
        ({"delete": [999]}, "No calendar entry with id 999 to delete"),
    ],
)
def test_a_suggestion_the_calendar_would_refuse_is_dropped_with_the_reason(tmp_db, suggested, why):
    _seed_history()
    before = _counts()
    coach = _suggest(**suggested)
    assert coach["suggestion"] is None and why in coach["suggestion_rejected"]
    assert coach["suggestion_rejected"]
    assert _counts() == before


def test_a_suggestion_that_collides_with_an_existing_entry_is_dropped(tmp_db):
    _seed_history()
    day = (FUTURE + timedelta(days=1)).isoformat()
    save_planned_workout(day, "Cross-Training", None, None, None, 30, "easy")
    coach = _suggest(set=[{"date": day, "workout_type": "Strength", "duration_min": 30}])
    assert coach["suggestion"] is None and "already has a scored" in coach["suggestion_rejected"]


def test_a_suggestion_on_a_blocked_day_is_dropped_whole(tmp_db):
    _seed_history()
    blocked = (FUTURE + timedelta(days=1)).isoformat()
    with Session(get_engine()) as s:
        crud.save_prefs(s, [blocked])
    coach = _suggest(
        set=[
            {
                "date": (FUTURE + timedelta(days=2)).isoformat(),
                "workout_type": "Strength",
                "duration_min": 30,
            },
            {"date": blocked, "workout_type": "Strength", "duration_min": 30},
        ]
    )
    assert coach["suggestion"] is None and "blocked" in coach["suggestion_rejected"]


@pytest.mark.parametrize(
    "item,why",
    [
        ({"workout_type": "Strength", "duration_min": "abc"}, "invalid duration_min"),
        ({"workout_type": "Strength", "duration_min": 45.5}, "invalid duration_min"),
        ({"workout_type": "Indoor Ride", "structure": "steady 60 min"}, "invalid structure"),
    ],
)
def test_a_suggestion_with_a_field_of_the_wrong_type_is_refused_by_name(tmp_db, item, why):
    """The coach's JSON is untrusted: a field the bulk endpoint would reject (a 422 at Apply with
    no reason shown) is refused here, naming the field."""
    _seed_history()
    later = (FUTURE + timedelta(days=2)).isoformat()
    coach = _suggest(set=[{"date": later, **item}])
    assert coach["suggestion"] is None and why in coach["suggestion_rejected"]


def test_a_numeric_string_duration_is_coerced_like_any_request_body(tmp_db):
    _seed_history()
    later = (FUTURE + timedelta(days=2)).isoformat()
    coach = _suggest(set=[{"date": later, "workout_type": "Strength", "duration_min": "45"}])
    assert coach["suggestion_rejected"] is None
    assert coach["suggestion"]["ops"][0]["duration_min"] == 45  # an int, as bulk would store it
    assert coach["suggestion"]["changes"][0]["hours"] == 0.75
