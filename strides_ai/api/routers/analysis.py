"""Deep-dive analysis endpoint."""

import asyncio
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlmodel import Session

from ...analysis import (
    DEEP_DIVE_SYSTEM_PROMPT,
    DEEP_DIVE_SYSTEM_PROMPT_LOCAL,
    RateLimitError,
    build_precomputed_brief,
    condense_streams_for_deep_dive,
    fetch_activity_streams,
)
from ...auth import get_access_token
from ...config import get_settings
from ...db import activities as crud
from ...db import get_all_memories, get_profile_fields
from ...db.engine import get_session
from ...hevy_analysis import LIFTING_DEEP_DIVE_SYSTEM_PROMPT
from ...profile import profile_to_text
from ..deps import get_backend

router = APIRouter()
log = logging.getLogger(__name__)


class DeepDiveResponse(BaseModel):
    activity_id: int
    report: str
    cached: bool
    completed_at: str | None
    model: str | None = None


class NotesRequest(BaseModel):
    notes: str


@router.patch("/activities/{activity_id}/notes", status_code=204)
async def save_notes(
    activity_id: int,
    body: NotesRequest,
    session: Session = Depends(get_session),
) -> None:
    """Persist user-authored notes for an activity."""
    if crud.get(session, activity_id) is None:
        raise HTTPException(status_code=404, detail="Activity not found")
    crud.update_analysis(session, activity_id, {"user_notes": body.notes})


@router.post("/activities/{activity_id}/deep-dive", response_model=DeepDiveResponse)
async def deep_dive(
    activity_id: int,
    request: Request,
    force: bool = False,
    session: Session = Depends(get_session),
    backend=Depends(get_backend),
) -> DeepDiveResponse:
    """
    Generate (or return cached) a deep-dive LLM analysis for a single activity.

    Set force=true to regenerate even if a cached report exists.
    """
    activity = crud.get(session, activity_id)
    if activity is None:
        raise HTTPException(status_code=404, detail="Activity not found")

    # Return cached report unless force=true
    if activity.deep_dive_report and not force:
        return DeepDiveResponse(
            activity_id=activity_id,
            report=activity.deep_dive_report,
            cached=True,
            completed_at=activity.deep_dive_completed_at,
            model=activity.deep_dive_model,
        )

    activity_dict = activity.model_dump()
    mode = getattr(request.app.state, "mode", "running")

    # ── Lifting (HEVY) deep dive — no Strava streams needed ──────────────
    if activity.sport_type == "WeightTraining":
        if not activity.exercises_json:
            raise HTTPException(
                status_code=422, detail="No exercise data available for this session"
            )

        system_prompt = LIFTING_DEEP_DIVE_SYSTEM_PROMPT
        try:
            exercises = json.loads(activity.exercises_json)
        except Exception:
            raise HTTPException(status_code=422, detail="Could not parse exercise data")

        lines = [f"Workout: {activity.name or 'Weight Training'}  |  Date: {activity.date}"]
        if activity.total_volume_kg:
            lines.append(
                f"Total volume: {activity.total_volume_kg:.0f} kg  |  Sets: {activity.total_sets or '?'}"
            )
        lines.append("")
        for ex in exercises:
            lines.append(f"### {ex.get('title') or ex.get('name', 'Exercise')}")
            for s in ex.get("sets", []):
                weight = f"{s['weight_kg']} kg" if s.get("weight_kg") is not None else "BW"
                reps = f"x{s['reps']}" if s.get("reps") is not None else ""
                rpe = f"  RPE {s['rpe']}" if s.get("rpe") is not None else ""
                stype = f"[{s['type']}]" if s.get("type") and s["type"] != "normal" else ""
                lines.append(f"  {stype} {weight} {reps}{rpe}".strip())
            lines.append("")
        user_content = "\n".join(lines)

        profile_text = profile_to_text(get_profile_fields(mode), mode)
        if profile_text:
            system_prompt += f"\n\n{profile_text}"

        memories = get_all_memories()
        if memories:
            mem_lines = "\n".join(f"  [{m['category']}] {m['content']}" for m in memories)
            system_prompt += (
                f"\n\n## Coaching Notes (remembered from previous sessions)\n{mem_lines}"
            )

        def _run_llm_lifting():
            return backend.stateless_turn(system_prompt, user_content, on_token=lambda _: None)

        try:
            report = await asyncio.get_event_loop().run_in_executor(None, _run_llm_lifting)
        except Exception as exc:
            log.error("LLM deep dive failed for lifting session %s: %s", activity_id, exc)
            raise HTTPException(status_code=500, detail="LLM analysis failed")

        completed_at = datetime.now(timezone.utc).isoformat()
        model_label = backend.label
        crud.update_analysis(
            session,
            activity_id,
            {
                "deep_dive_report": report,
                "deep_dive_completed_at": completed_at,
                "deep_dive_model": model_label,
            },
        )
        return DeepDiveResponse(
            activity_id=activity_id,
            report=report,
            cached=False,
            completed_at=completed_at,
            model=model_label,
        )

    # ── Cardio (Strava) deep dive ─────────────────────────────────────────
    settings = get_settings()
    if not settings.strava_client_id or not settings.strava_client_secret:
        raise HTTPException(status_code=500, detail="Strava credentials not configured")
    try:
        access_token = get_access_token(settings.strava_client_id, settings.strava_client_secret)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Could not get Strava token: {exc}")

    try:
        streams = fetch_activity_streams(activity_id, access_token)
    except RateLimitError:
        raise HTTPException(status_code=429, detail="Strava rate limit reached — try again shortly")
    except Exception as exc:
        log.error("stream fetch error for deep dive %s: %s", activity_id, exc)
        raise HTTPException(status_code=502, detail="Failed to fetch stream data from Strava")

    if not streams:
        raise HTTPException(
            status_code=422,
            detail="No stream data available for this activity (manual entry or GPS disabled)",
        )

    if backend.prefers_precomputed_brief:
        system_prompt = DEEP_DIVE_SYSTEM_PROMPT_LOCAL
        user_content = build_precomputed_brief(streams, activity_dict)
    else:
        system_prompt = DEEP_DIVE_SYSTEM_PROMPT
        user_content = condense_streams_for_deep_dive(streams, activity_dict)

    profile_text = profile_to_text(get_profile_fields(mode), mode)
    if profile_text:
        system_prompt += f"\n\n{profile_text}"

    memories = get_all_memories()
    if memories:
        mem_lines = "\n".join(f"  [{m['category']}] {m['content']}" for m in memories)
        system_prompt += f"\n\n## Coaching Notes (remembered from previous sessions)\n{mem_lines}"

    def _run_llm():
        return backend.stateless_turn(
            system_prompt,
            user_content,
            on_token=lambda _: None,
        )

    try:
        report = await asyncio.get_event_loop().run_in_executor(None, _run_llm)
    except Exception as exc:
        log.error("LLM deep dive failed for activity %s: %s", activity_id, exc)
        raise HTTPException(status_code=500, detail="LLM analysis failed")

    completed_at = datetime.now(timezone.utc).isoformat()
    model_label = backend.label
    crud.update_analysis(
        session,
        activity_id,
        {
            "deep_dive_report": report,
            "deep_dive_completed_at": completed_at,
            "deep_dive_model": model_label,
        },
    )

    return DeepDiveResponse(
        activity_id=activity_id,
        report=report,
        cached=False,
        completed_at=completed_at,
        model=model_label,
    )
