"""Calendar preferences and training plan CRUD operations."""

import json
from datetime import date as date_cls, timedelta

import sqlalchemy as sa
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlmodel import Session, select

from ..workout_structure import structure_for_type, structure_to_json, total_seconds
from .models import CalendarPref, TrainingPlan

# Race-type planned workouts are the only source of "races". Mirrors the race entries in
# web/src/pages/calendar/constants.ts (WORKOUT_TYPE_GROUPS); "Race" is the legacy generic type.
RACE_WORKOUT_TYPES = frozenset({"Running Race", "Cycling Race", "Race"})


def races_from_plan(plan_rows: list[dict]) -> list[dict]:
    """``{date, name}`` for every race-type workout, sorted by date. The name is the workout
    description (``"Race"`` when blank). There is no target-time column, so none is returned."""
    races = [
        {"date": w["date"], "name": (w.get("description") or "").strip() or "Race"}
        for w in plan_rows
        if w.get("workout_type") in RACE_WORKOUT_TYPES
    ]
    return sorted(races, key=lambda r: r["date"])


def get_races(session: Session) -> list[dict]:
    stmt = select(TrainingPlan).where(TrainingPlan.workout_type.in_(RACE_WORKOUT_TYPES))
    return races_from_plan([w.model_dump() for w in session.exec(stmt).all()])


def get_prefs(session: Session) -> dict:
    """Blocked days plus ``races`` derived from the plan (all of them, past included; consumers
    filter). The legacy ``calendar_prefs.races`` column is no longer read."""
    row = session.get(CalendarPref, 1)
    return {
        "blocked_days": json.loads(row.blocked_days) if row else [],
        "races": get_races(session),
    }


def save_prefs(session: Session, blocked_days: list) -> None:
    stmt = sqlite_insert(CalendarPref).values(id=1, blocked_days=json.dumps(blocked_days))
    stmt = stmt.on_conflict_do_update(
        index_elements=["id"],
        set_={"blocked_days": json.dumps(blocked_days)},
    )
    session.execute(stmt)
    session.commit()


def get_plan(
    session: Session,
    start_date: str | None = None,
    end_date: str | None = None,
) -> list[TrainingPlan]:
    stmt = select(TrainingPlan).order_by(TrainingPlan.date)
    if start_date and end_date:
        stmt = stmt.where(TrainingPlan.date.between(start_date, end_date))
    return session.exec(stmt).all()


def save_planned_workout(
    session: Session,
    date: str,
    workout_type: str,
    description: str | None,
    distance_km: float | None,
    elevation_m: float | None,
    duration_min: int | None,
    intensity: str | None,
    route_url: str | None = None,
    structure: dict | None = None,
) -> None:
    """Upsert a user-entered planned workout.

    ``structure`` (cycling types only) is validated here, so every write path gets the same
    rules; a valid one is authoritative for ``duration_min``. Omitting it clears any structure.
    """
    structure = structure_for_type(workout_type, structure)
    if structure:
        duration_min = round(total_seconds(structure) / 60)
    structure_json = structure_to_json(structure)
    stmt = sqlite_insert(TrainingPlan).values(
        date=date,
        workout_type=workout_type,
        description=description,
        distance_km=distance_km,
        elevation_m=elevation_m,
        duration_min=duration_min,
        intensity=intensity,
        route_url=route_url,
        structure_json=structure_json,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["date"],
        set_={
            "workout_type": workout_type,
            "description": description,
            "distance_km": distance_km,
            "elevation_m": elevation_m,
            "duration_min": duration_min,
            "intensity": intensity,
            "route_url": route_url,
            "structure_json": structure_json,
            "nutrition_json": None,
            "route_analysis_json": None,
            "route_analyzed_at": None,
            "route_analysis_model": None,
            "created_at": sa.text("datetime('now')"),
        },
    )
    session.execute(stmt)
    session.commit()


def delete_planned_workout(session: Session, date: str) -> None:
    row = session.get(TrainingPlan, date)
    if row:
        session.delete(row)
        session.commit()


def save_workout_nutrition(session: Session, date: str, nutrition: dict) -> None:
    row = session.get(TrainingPlan, date)
    if row:
        row.nutrition_json = json.dumps(nutrition)
        session.add(row)
        session.commit()


def save_route_analysis(
    session: Session, date: str, analysis: dict, analyzed_at: str, model: str
) -> None:
    row = session.get(TrainingPlan, date)
    if row:
        row.route_analysis_json = json.dumps(analysis)
        row.route_analyzed_at = analyzed_at
        row.route_analysis_model = model
        session.add(row)
        session.commit()


def get_upcoming_workouts(session: Session, days: int = 14) -> list[TrainingPlan]:
    """Return planned workouts from today through the next *days* days."""
    today = date_cls.today().isoformat()
    end = (date_cls.today() + timedelta(days=days)).isoformat()
    stmt = (
        select(TrainingPlan)
        .where(TrainingPlan.date >= today, TrainingPlan.date <= end)
        .order_by(TrainingPlan.date)
    )
    return session.exec(stmt).all()
