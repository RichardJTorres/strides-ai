"""Calendar routes."""

import asyncio
import json
import logging
from datetime import date as date_cls, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlmodel import Session

from ... import compliance
from ... import kinds
from ...config import VALID_MODES, get_settings
from ...coach import RECENT_ACTIVITIES_IN_SYSTEM
from ...db import activities as act_crud
from ...db import calendar as crud
from ...db import memories as mem_crud
from ...db import profiles as prof_crud
from ...db.engine import get_session
from ...plan_generation import (
    SURROUNDING_WINDOW_DAYS,
    build_plan_generation_prompt,
    parse_plan_generation_response,
    plan_generation_system_prompt,
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
from ...training_state import build_training_state, check_plan_changes, render_for_prompt
from ...units import UnitSystem
from ...workout_structure import render_text, structure_from_json, to_zwo, zwo_filename
from ..deps import get_backend, get_units

logger = logging.getLogger(__name__)

router = APIRouter()


class CalendarPrefsBody(BaseModel):
    blocked_days: list[str] = []


class EntryBody(BaseModel):
    """Create / patch body. On PATCH only the fields actually sent are applied (an explicit
    null clears the field); ``kind`` cannot change after create."""

    date: str | None = None
    kind: str | None = None
    title: str | None = None
    notes: str | None = None
    # Convenience for generated plans and older clients: the old single free-text field. It
    # becomes the objective (workout), the name (race) or the notes (anything else).
    description: str | None = None
    # workout
    workout_type: str | None = None
    objective: str | None = None
    distance_km: float | None = None
    elevation_m: float | None = None
    duration_min: int | None = None
    intensity: str | None = None
    route_url: str | None = None
    structure: dict | None = None
    # race
    sport: str | None = None
    goal_time_s: int | None = None
    goal_text: str | None = None
    priority: str | None = None
    result_activity_id: int | None = None
    result_time_s: int | None = None


class ChangeOp(EntryBody):
    op: str
    id: int | None = None


class BulkBody(BaseModel):
    ops: list[ChangeOp]
    request_id: str | None = None


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
    structure: dict | None = None
    structure_text: str | None = None


class GeneratePlanResponse(BaseModel):
    workouts: list[GeneratedWorkout]
    summary: str = ""
    warnings: list[str] = []


@router.get("/calendar/prefs")
def get_calendar_prefs(session: Session = Depends(get_session)):
    return crud.get_prefs(session)


@router.put("/calendar/prefs")
def put_calendar_prefs(body: CalendarPrefsBody, session: Session = Depends(get_session)):
    crud.save_prefs(session, body.blocked_days)
    return {"status": "ok"}


@router.get("/calendar/training-state")
def get_training_state(
    request: Request,
    mode: str | None = None,
    session: Session = Depends(get_session),
    units: UnitSystem = Depends(get_units),
):
    """Current load, planned-load projection, weekly ramp and plan conflicts (training_state.py)."""
    mode = mode or getattr(request.app.state, "mode", "running")
    if mode not in VALID_MODES or mode == "lifting":
        mode = "running"
    rows = [r.model_dump() for r in act_crud.get_for_mode(session, mode)]
    plan_rows = crud.get_plan_rows(session)
    return build_training_state(
        rows, plan_rows, crud.get_prefs(session), mode, units, date_cls.today()
    ).to_dict()


def _plan_row(data: dict) -> dict:
    """An entry for the API: stored structure_json is exposed parsed as ``structure``."""
    data = dict(data)
    structure = structure_from_json(data.pop("structure_json", None))
    data["structure"] = structure
    data["structure_text"] = render_text(structure) if structure else None
    return data


def _normalize_entry_data(data: dict, creating: bool) -> dict:
    """Resolve the legacy shape (`workout_type` "Race"/"Running Race"/"Rest", `description`) into
    kind + detail fields, so generated plans and older clients need no special casing."""
    data = dict(data)
    wtype = data.get("workout_type")
    if creating and not data.get("kind"):
        if kinds.race_sport_for_legacy_type(wtype):
            data["kind"] = kinds.KIND_RACE
            data.setdefault("sport", kinds.race_sport_for_legacy_type(wtype))
        elif wtype == kinds.LEGACY_REST_TYPE:
            data["kind"] = kinds.KIND_REST
        else:
            data["kind"] = kinds.KIND_WORKOUT
    kind = data.get("kind")
    if kind in (kinds.KIND_RACE, kinds.KIND_REST):
        data.pop("workout_type", None)
    if kind == kinds.KIND_REST:
        for key in ("intensity", "distance_km", "elevation_m", "duration_min", "structure"):
            data.pop(key, None)
    if "description" in data:
        text = data.pop("description")
        target = {kinds.KIND_WORKOUT: "objective", kinds.KIND_RACE: "title"}.get(kind, "notes")
        data.setdefault(target, text)
    return data


def _entry_or_404(session: Session, entry_id: int) -> dict:
    row = crud.get_entry(session, entry_id)
    if row is None:
        raise HTTPException(status_code=404, detail="No calendar entry with this id")
    return row


def _write(fn, *args):
    try:
        return fn(*args)
    except crud.EntryNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except crud.EntryError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/calendar/kinds")
def get_kinds():
    """The calendar taxonomy (kinds, workout types, race sports) — the frontend declares none."""
    return kinds.taxonomy()


@router.get("/calendar/entries")
def get_calendar_entries(
    start_date: str | None = None,
    end_date: str | None = None,
    session: Session = Depends(get_session),
):
    return [_plan_row(r) for r in crud.get_plan_rows(session, start_date, end_date)]


@router.get("/calendar/compliance")
def get_compliance(
    start_date: str,
    end_date: str,
    session: Session = Depends(get_session),
    units: UnitSystem = Depends(get_units),
):
    """Compute plan-vs-actual compliance for a date range, mirroring the same computation the
    coach's system prompt uses (strides_ai/coach.py:_compliance_section) so the Calendar UI and
    the coach can never disagree about what counts as completed/modified/missed."""
    try:
        start = date_cls.fromisoformat(start_date)
        end = date_cls.fromisoformat(end_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="start_date/end_date must be YYYY-MM-DD")
    if start > end:
        raise HTTPException(status_code=400, detail="start_date must be on or before end_date")

    plan_rows = crud.get_plan_rows(session, start_date, end_date)
    activity_rows = [
        r.model_dump()
        for r in act_crud.get_all(session)
        if start_date <= (r.date or "") <= end_date
    ]
    days = compliance.compliance_for_range(
        plan_rows, activity_rows, start, end, date_cls.today(), units
    )
    summary = compliance.summarize_compliance(days)

    return {
        "days": [
            {
                "date": d.date.isoformat(),
                "entry_id": d.entry_id,
                "workout_type": d.workout_type,
                "status": d.status.value,
                "planned_distance_km": d.planned_distance_km,
                "actual_distance_km": d.actual_distance_km,
                "matched_activity_id": d.matched_activity_id,
                "note": d.note,
            }
            for d in days
        ],
        "summary": {
            "total_scored": summary.total_scored,
            "completed": summary.completed,
            "modified": summary.modified,
            "missed": summary.missed,
            "unscored": summary.unscored,
            "upcoming": summary.upcoming,
            "consistency_pct": summary.consistency_pct,
            "on_target_pct": summary.on_target_pct,
        },
    }


@router.post("/calendar/entries")
def create_calendar_entry(body: EntryBody, session: Session = Depends(get_session)):
    return _plan_row(
        _write(
            crud.create_entry,
            session,
            _normalize_entry_data(body.model_dump(exclude_unset=True), True),
        )
    )


@router.patch("/calendar/entries/{entry_id}")
def patch_calendar_entry(entry_id: int, body: EntryBody, session: Session = Depends(get_session)):
    existing = _entry_or_404(session, entry_id)
    if body.kind is not None and body.kind != existing["kind"]:
        raise HTTPException(
            status_code=400, detail="An entry's kind cannot change; delete it and add a new one"
        )
    patch = _normalize_entry_data(
        {**body.model_dump(exclude_unset=True), "kind": existing["kind"]}, False
    )
    return _plan_row(_write(crud.update_entry, session, entry_id, patch))


@router.delete("/calendar/entries/{entry_id}")
def delete_calendar_entry(entry_id: int, session: Session = Depends(get_session)):
    crud.delete_entry(session, entry_id)
    return {"status": "ok"}


@router.post("/calendar/entries/bulk")
def bulk_calendar_entries(body: BulkBody, session: Session = Depends(get_session)):
    """Atomic, idempotent change set (accepting a generated block, bulk edits). All operations
    apply or none do; resending the same ``request_id`` returns the first result."""
    ops = []
    for o in body.ops:
        data = o.model_dump(exclude_unset=True)
        if data.get("id") is None:
            data.pop("id", None)
        op = data.pop("op")
        ops.append({"op": op, **_normalize_entry_data(data, op == "create")})
    result = _write(crud.apply_changes, session, ops, body.request_id)
    return {"status": "ok", **result}


@router.get("/calendar/entries/{entry_id}/zwo")
def download_zwo(entry_id: int, session: Session = Depends(get_session)):
    """Zwift workout file for a planned workout that has a structure."""
    row = _entry_or_404(session, entry_id)
    structure = structure_from_json(row.get("structure_json"))
    if not structure:
        raise HTTPException(status_code=404, detail="No structured workout on this entry")
    name = f"{row['workout_type']} {row['date']}"
    return Response(
        content=to_zwo(structure, name, row.get("objective")),
        media_type="application/xml",
        headers={
            "Content-Disposition": f'attachment; filename="{zwo_filename(row["date"], name)}"'
        },
    )


def _apply_guardrails(result, mode_rows, plan_rows, prefs, mode, units, today) -> dict:
    """Drop generated workouts on blocked-out/race days (a prompt-only rule the model can break)
    and report load warnings (ramp, projected ratio) without changing the proposal."""
    if mode == "lifting":
        return result
    violations = check_plan_changes(
        mode_rows, plan_rows, prefs, mode, units, today, {"set": result["workouts"]}
    )
    hard_dates = {v.date for v in violations if v.hard}
    result["workouts"] = [w for w in result["workouts"] if w["date"] not in hard_dates]
    result["warnings"] = [
        f"Removed {v.date}: {v.detail}" if v.hard else v.detail for v in violations
    ]
    return result


@router.post("/calendar/generate-plan", response_model=GeneratePlanResponse)
async def generate_plan(
    body: GeneratePlanBody,
    request: Request,
    session: Session = Depends(get_session),
    backend=Depends(get_backend),
    units: UnitSystem = Depends(get_units),
):
    """Generate a suggested training block for a date range. Does not write to the calendar —
    the frontend accepts the result via POST /calendar/entries/bulk."""
    try:
        start = date_cls.fromisoformat(body.start_date)
        end = date_cls.fromisoformat(body.end_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="start_date/end_date must be YYYY-MM-DD")
    if start > end:
        raise HTTPException(status_code=400, detail="start_date must be on or before end_date")

    mode = getattr(request.app.state, "mode", "running")
    profile_fields = prof_crud.get_fields(session, mode)
    profile_text = profile_to_text(profile_fields, mode, units)
    memories = [m.model_dump() for m in mem_crud.get_all(session)]
    prefs = crud.get_prefs(session)

    padded_start = (start - timedelta(days=SURROUNDING_WINDOW_DAYS)).isoformat()
    padded_end = (end + timedelta(days=SURROUNDING_WINDOW_DAYS)).isoformat()
    surrounding = crud.get_plan_rows(session, padded_start, padded_end)

    recent_activities = [a.model_dump() for a in act_crud.get_all(session)][
        :RECENT_ACTIVITIES_IN_SYSTEM
    ]
    mode_rows = [a.model_dump() for a in act_crud.get_for_mode(session, mode)]
    all_plan = crud.get_plan_rows(session)
    today = date_cls.today()
    training_state_text = (
        render_for_prompt(
            build_training_state(mode_rows, all_plan, prefs, mode, units, today), units
        )
        if mode in VALID_MODES and mode != "lifting"
        else ""
    )

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
        units,
        training_state_text,
    )

    def _run_llm():
        return backend.stateless_turn(
            plan_generation_system_prompt(units),
            prompt,
            on_token=lambda _: None,
            source="plan_generation",
        )

    text = ""
    try:
        text = await asyncio.get_event_loop().run_in_executor(None, _run_llm)
        result = parse_plan_generation_response(text, body.start_date, body.end_date, units)
        result = _apply_guardrails(result, mode_rows, all_plan, prefs, mode, units, today)
        for w in result["workouts"]:
            w["structure_text"] = render_text(w["structure"]) if w.get("structure") else None
        return result
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        logger.error(
            "Plan generation parse failure (%s); raw response (%d chars): %r",
            exc,
            len(text),
            text[:2000],
        )
        if not text.strip():
            detail = "The model returned an empty response. Please try again."
        else:
            detail = (
                f"Failed to parse generated plan: {exc}. Response began: {text.strip()[:200]!r}"
            )
        raise HTTPException(status_code=502, detail=detail)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Plan generation failed: {exc}")


@router.post("/calendar/entries/{entry_id}/nutrition")
def analyze_workout_nutrition(
    entry_id: int,
    request: Request,
    session: Session = Depends(get_session),
    units: UnitSystem = Depends(get_units),
):
    api_key = get_settings().anthropic_api_key
    if not api_key:
        raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY not set")

    workout = _entry_or_404(session, entry_id)
    if workout["kind"] not in (kinds.KIND_WORKOUT, kinds.KIND_RACE):
        raise HTTPException(
            status_code=400, detail="Nutrition advice applies to workouts and races"
        )

    mode = getattr(request.app.state, "mode", "running")
    profile_fields = prof_crud.get_fields(session, mode)
    profile_text = profile_to_text(profile_fields, mode, units)

    nutrition = analyze_nutrition(workout, profile_text, api_key, units)
    # Rejected (not saved) if the entry changed while the model was working.
    crud.save_workout_nutrition(
        session, entry_id, nutrition, workout.get("inputs_hash") or crud.inputs_hash(workout)
    )
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


@router.post("/calendar/entries/{entry_id}/analyze-route")
async def analyze_workout_route(
    entry_id: int,
    request: Request,
    force: bool = False,
    session: Session = Depends(get_session),
    backend=Depends(get_backend),
    units: UnitSystem = Depends(get_units),
):
    """Fetch the workout's route (Strava or RideWithGPS) and judge whether it fits the
    workout's goal."""
    workout = _entry_or_404(session, entry_id)
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
    profile_text = profile_to_text(profile_fields, mode, units)

    prompt = build_route_analysis_prompt(
        workout, route_detail, elevation_profile, profile_text, units
    )

    def _run_llm():
        return backend.stateless_turn(
            ROUTE_ANALYSIS_SYSTEM_PROMPT, prompt, on_token=lambda _: None, source="route_analysis"
        )

    try:
        text = await asyncio.get_event_loop().run_in_executor(None, _run_llm)
        analysis = parse_route_analysis_response(text)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=502, detail=f"Failed to parse route analysis: {exc}")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Route analysis failed: {exc}")

    analyzed_at = datetime.now(timezone.utc).isoformat()
    crud.save_route_analysis(
        session,
        entry_id,
        analysis,
        analyzed_at,
        backend.label,
        workout.get("inputs_hash") or crud.inputs_hash(workout),
    )
    return {"cached": False, "analyzed_at": analyzed_at, "model": backend.label, **analysis}
