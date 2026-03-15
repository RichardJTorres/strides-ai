"""Calendar routes."""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlmodel import Session

from ...config import get_settings
from ...db import calendar as crud
from ...db import profiles as prof_crud
from ...db.engine import get_session
from ...profile import profile_to_text
from ...schedule import analyze_nutrition

router = APIRouter()


class CalendarPrefsBody(BaseModel):
    blocked_days: list[str] = []
    races: list[dict] = []


class WorkoutBody(BaseModel):
    workout_type: str
    description: str | None = None
    distance_km: float | None = None
    elevation_m: float | None = None
    duration_min: int | None = None
    intensity: str | None = None


@router.get("/calendar/prefs")
def get_calendar_prefs(session: Session = Depends(get_session)):
    return crud.get_prefs(session)


@router.put("/calendar/prefs")
def put_calendar_prefs(body: CalendarPrefsBody, session: Session = Depends(get_session)):
    crud.save_prefs(session, body.blocked_days, body.races)
    return {"status": "ok"}


@router.get("/calendar/plan")
def get_calendar_plan(session: Session = Depends(get_session)):
    return [r.model_dump() for r in crud.get_plan(session)]


@router.put("/calendar/plan/{date}")
def put_planned_workout(date: str, body: WorkoutBody, session: Session = Depends(get_session)):
    crud.save_planned_workout(
        session,
        date,
        body.workout_type,
        body.description,
        body.distance_km,
        body.elevation_m,
        body.duration_min,
        body.intensity,
    )
    return {"status": "ok", "date": date}


@router.delete("/calendar/plan/{date}")
def delete_planned_workout(date: str, session: Session = Depends(get_session)):
    crud.delete_planned_workout(session, date)
    return {"status": "ok"}


@router.post("/calendar/plan/{date}/nutrition")
def analyze_workout_nutrition(
    date: str,
    request: Request,
    session: Session = Depends(get_session),
):
    api_key = get_settings().anthropic_api_key
    if not api_key:
        raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY not set")

    plan = crud.get_plan(session)
    workout = next((w.model_dump() for w in plan if w.date == date), None)
    if not workout:
        raise HTTPException(status_code=404, detail="No planned workout found for this date")

    mode = getattr(request.app.state, "mode", "running")
    profile_fields = prof_crud.get_fields(session, mode)
    profile_text = profile_to_text(profile_fields, mode)

    nutrition = analyze_nutrition(workout, profile_text, api_key)
    crud.save_workout_nutrition(session, date, nutrition)
    return nutrition
