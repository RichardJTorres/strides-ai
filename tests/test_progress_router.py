"""Tests for GET /api/progress — calls the handler directly with an explicit session."""

from datetime import date, timedelta

from sqlmodel import Session

from tests.plan_helpers import save_planned_workout, save_races
from strides_ai import db
from strides_ai.analytics.aggregation import monday_of
from strides_ai.api.routers.progress import progress
from strides_ai.db.engine import get_engine
from strides_ai.units import UnitSystem


def _call(units=UnitSystem.METRIC):
    with Session(get_engine()) as session:
        return progress(session=session, units=units)


def test_empty_database(tmp_db):
    result = _call()
    assert result.as_of == date.today().isoformat()
    assert result.week_start == monday_of(date.today()).isoformat()
    assert result.streak.model_dump() == {
        "weeks": 0,
        "best_weeks": 0,
        "max_misses": 1,
        "this_week": {"done": 0, "missed": 0, "upcoming": 0, "status": "no_plan"},
    }
    assert result.records == []


def test_reads_plan_and_activities_from_the_db(tmp_db, sample_activity):
    last_week = monday_of(date.today()) - timedelta(days=5)
    save_planned_workout(last_week.isoformat(), "Easy Run", None, 5.0, None, 30, "easy")
    db.upsert_activity(
        {**sample_activity, "start_date_local": f"{last_week.isoformat()}T07:00:00Z"}
    )
    result = _call(UnitSystem.IMPERIAL)
    assert result.unit_system == "imperial"
    assert (result.streak.weeks, result.streak.best_weeks) == (1, 1)


def test_monthly_progression_reads_every_activity_of_the_sport(tmp_db, sample_activity):
    from strides_ai.api.routers.progress import progress_months

    day = date.today() - timedelta(days=40)
    db.upsert_activity({**sample_activity, "start_date_local": f"{day.isoformat()}T07:00:00Z"})
    with Session(get_engine()) as session:
        runs = progress_months(sport="run", months=24, session=session)
        rides = progress_months(sport="ride", months=24, session=session)
    assert runs.months[0].in_progress and runs.first_date == day.isoformat()
    assert sum(m.activities for m in runs.months) == 1
    peak = next(m.longest for m in runs.months if m.activities)
    assert peak.activity_id == sample_activity["id"] and peak.value > 0
    assert rides.months == [] and rides.first_date is None
