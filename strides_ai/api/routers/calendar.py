"""Calendar routes."""

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ... import db
from ...config import get_settings
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
def get_calendar_prefs():
    return db.get_calendar_prefs()


@router.put("/calendar/prefs")
def put_calendar_prefs(body: CalendarPrefsBody):
    db.save_calendar_prefs(body.blocked_days, body.races)
    return {"status": "ok"}


@router.get("/calendar/plan")
def get_calendar_plan():
    return db.get_training_plan()


@router.put("/calendar/plan/{date}")
def put_planned_workout(date: str, body: WorkoutBody):
    db.save_planned_workout(
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
def delete_planned_workout(date: str):
    db.delete_planned_workout(date)
    return {"status": "ok"}


@router.post("/calendar/plan/{date}/nutrition")
def analyze_workout_nutrition(date: str, request: Request):

    api_key = get_settings().anthropic_api_key
    if not api_key:
        raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY not set")

    plan = db.get_training_plan()
    workout = next((w for w in plan if w["date"] == date), None)
    if not workout:
        raise HTTPException(status_code=404, detail="No planned workout found for this date")

    mode = getattr(request.app.state, "mode", "running")
    profile_fields = db.get_profile_fields(mode)
    profile_text = profile_to_text(profile_fields, mode)

    nutrition = analyze_nutrition(workout, profile_text, api_key)
    db.save_workout_nutrition(date, nutrition)
    return nutrition
