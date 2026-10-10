"""Calendar routes."""

import asyncio
import json
from datetime import date as date_cls, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlmodel import Session

from ...config import get_settings
from ...coach import RECENT_ACTIVITIES_IN_SYSTEM
from ...db import activities as act_crud
from ...db import calendar as crud
from ...db import memories as mem_crud
from ...db import profiles as prof_crud
from ...db.engine import get_session
from ...plan_generation import (
    PLAN_GENERATION_SYSTEM_PROMPT,
    SURROUNDING_WINDOW_DAYS,
    build_plan_generation_prompt,
    parse_plan_generation_response,
)
from ...profile import profile_to_text
from ...route_analysis import (
    ROUTE_ANALYSIS_SYSTEM_PROMPT,
    build_route_analysis_prompt,
    parse_route_analysis_response,
)
from ...schedule import analyze_nutrition
from ...sources.base import AuthError, ConfigurationError, NoDataError
from ...sources.ridewithgps import condense_elevation_profile
from ...sources.routes import fetch_route_detail, fetch_route_summary
from ..deps import get_backend

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
    route_url: str | None = None


class BulkWorkoutEntry(WorkoutBody):
    date: str


class BulkPlanBody(BaseModel):
    set: list[BulkWorkoutEntry] = []
    delete: list[str] = []


class GeneratePlanBody(BaseModel):
    start_date: str
    end_date: str
    freeform_text: str = ""


class GeneratedWorkout(BaseModel):
    date: str
    workout_type: str
    description: str | None = None
    distance_km: float | None = None
    elevation_m: float | None = None
    duration_min: int | None = None
    intensity: str | None = None


class GeneratePlanResponse(BaseModel):
    workouts: list[GeneratedWorkout]
    summary: str = ""


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
        body.route_url,
    )
    return {"status": "ok", "date": date}


@router.delete("/calendar/plan/{date}")
def delete_planned_workout(date: str, session: Session = Depends(get_session)):
    crud.delete_planned_workout(session, date)
    return {"status": "ok"}


@router.post("/calendar/plan/bulk")
def bulk_update_plan(body: BulkPlanBody, session: Session = Depends(get_session)):
    """Apply multiple workout upserts/deletes in one call (used to accept a generated block)."""
    for w in body.set:
        crud.save_planned_workout(
            session,
            w.date,
            w.workout_type,
            w.description,
            w.distance_km,
            w.elevation_m,
            w.duration_min,
            w.intensity,
            w.route_url,
        )
    for date in body.delete:
        crud.delete_planned_workout(session, date)
    return {"status": "ok", "set": len(body.set), "deleted": len(body.delete)}


@router.post("/calendar/generate-plan", response_model=GeneratePlanResponse)
async def generate_plan(
    body: GeneratePlanBody,
    request: Request,
    session: Session = Depends(get_session),
    backend=Depends(get_backend),
):
    """Generate a suggested training block for a date range. Does not write to the calendar —
    the frontend accepts the result via POST /calendar/plan/bulk."""
    try:
        start = date_cls.fromisoformat(body.start_date)
        end = date_cls.fromisoformat(body.end_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="start_date/end_date must be YYYY-MM-DD")
    if start > end:
        raise HTTPException(status_code=400, detail="start_date must be on or before end_date")

    mode = getattr(request.app.state, "mode", "running")
    profile_fields = prof_crud.get_fields(session, mode)
    profile_text = profile_to_text(profile_fields, mode)
    memories = [m.model_dump() for m in mem_crud.get_all(session)]
    prefs = crud.get_prefs(session)

    padded_start = (start - timedelta(days=SURROUNDING_WINDOW_DAYS)).isoformat()
    padded_end = (end + timedelta(days=SURROUNDING_WINDOW_DAYS)).isoformat()
    surrounding = [w.model_dump() for w in crud.get_plan(session, padded_start, padded_end)]

    recent_activities = [a.model_dump() for a in act_crud.get_all(session)][
        :RECENT_ACTIVITIES_IN_SYSTEM
    ]

    prompt = build_plan_generation_prompt(
        mode,
        profile_text,
        memories,
        prefs,
        surrounding,
        recent_activities,
        body.start_date,
        body.end_date,
        body.freeform_text,
    )

    def _run_llm():
        return backend.stateless_turn(
            PLAN_GENERATION_SYSTEM_PROMPT, prompt, on_token=lambda _: None
        )

    try:
        text = await asyncio.get_event_loop().run_in_executor(None, _run_llm)
        return parse_plan_generation_response(text, body.start_date, body.end_date)
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise HTTPException(status_code=502, detail=f"Failed to parse generated plan: {exc}")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Plan generation failed: {exc}")


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


@router.get("/calendar/route-preview")
def route_preview(url: str):
    """Look up a route's headline stats (Strava or RideWithGPS), used to autofill
    distance/elevation while the athlete is still typing a route URL into a workout form (no
    date/workout required, and nothing is persisted)."""
    try:
        return fetch_route_summary(url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except NoDataError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ConfigurationError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    except AuthError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.post("/calendar/plan/{date}/analyze-route")
async def analyze_workout_route(
    date: str,
    request: Request,
    force: bool = False,
    session: Session = Depends(get_session),
    backend=Depends(get_backend),
):
    """Fetch the workout's route (Strava or RideWithGPS) and judge whether it fits the
    workout's goal."""
    plan = crud.get_plan(session)
    workout = next((w.model_dump() for w in plan if w.date == date), None)
    if not workout:
        raise HTTPException(status_code=404, detail="No planned workout found for this date")
    if not workout.get("route_url"):
        raise HTTPException(status_code=400, detail="No route URL attached to this workout")

    if workout.get("route_analysis_json") and not force:
        return {
            "cached": True,
            "analyzed_at": workout.get("route_analyzed_at"),
            "model": workout.get("route_analysis_model"),
            **json.loads(workout["route_analysis_json"]),
        }

    try:
        route_detail = fetch_route_detail(workout["route_url"])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except NoDataError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ConfigurationError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    except AuthError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    elevation_profile = condense_elevation_profile(route_detail["track_points"])

    mode = getattr(request.app.state, "mode", "running")
    profile_fields = prof_crud.get_fields(session, mode)
    profile_text = profile_to_text(profile_fields, mode)

    prompt = build_route_analysis_prompt(workout, route_detail, elevation_profile, profile_text)

    def _run_llm():
        return backend.stateless_turn(ROUTE_ANALYSIS_SYSTEM_PROMPT, prompt, on_token=lambda _: None)

    try:
        text = await asyncio.get_event_loop().run_in_executor(None, _run_llm)
        analysis = parse_route_analysis_response(text)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=502, detail=f"Failed to parse route analysis: {exc}")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Route analysis failed: {exc}")

    analyzed_at = datetime.now(timezone.utc).isoformat()
    crud.save_route_analysis(session, date, analysis, analyzed_at, backend.label)
    return {"cached": False, "analyzed_at": analyzed_at, "model": backend.label, **analysis}
