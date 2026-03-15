"""Calendar preferences and training plan CRUD operations."""

import json
from datetime import date as date_cls, timedelta

import sqlalchemy as sa
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlmodel import Session, select

from .models import CalendarPref, TrainingPlan


def get_prefs(session: Session) -> dict:
    row = session.get(CalendarPref, 1)
    if row is None:
        return {"blocked_days": [], "races": []}
    return {
        "blocked_days": json.loads(row.blocked_days),
        "races": json.loads(row.races),
    }


def save_prefs(session: Session, blocked_days: list, races: list) -> None:
    stmt = sqlite_insert(CalendarPref).values(
        id=1,
        blocked_days=json.dumps(blocked_days),
        races=json.dumps(races),
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["id"],
        set_={
            "blocked_days": json.dumps(blocked_days),
            "races": json.dumps(races),
        },
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
) -> None:
    """Upsert a user-entered planned workout."""
    stmt = sqlite_insert(TrainingPlan).values(
        date=date,
        workout_type=workout_type,
        description=description,
        distance_km=distance_km,
        elevation_m=elevation_m,
        duration_min=duration_min,
        intensity=intensity,
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
            "nutrition_json": None,
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
