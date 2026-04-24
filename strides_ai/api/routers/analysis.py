"""Deep-dive analysis endpoint."""

import asyncio
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlmodel import Session

from ...analysis import RateLimitError
from ...db import activities as crud
from ...db import get_all_memories, get_profile_fields
from ...db.engine import get_session
from ...profile import profile_to_text
from ...sources import get_source_for_activity
from ...sources.base import AuthError, ConfigurationError, NoDataError
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

    if activity.deep_dive_report and not force:
        return DeepDiveResponse(
            activity_id=activity_id,
            report=activity.deep_dive_report,
            cached=True,
            completed_at=activity.deep_dive_completed_at,
            model=activity.deep_dive_model,
        )

    mode = getattr(request.app.state, "mode", "running")
    source = get_source_for_activity(activity)

    try:
        system_prompt, user_content = source.build_deep_dive_content(activity, backend)
    except ConfigurationError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    except AuthError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except RateLimitError:
        raise HTTPException(status_code=429, detail="Rate limit reached — try again shortly")
    except NoDataError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        log.error("deep dive source error for activity %s: %s", activity_id, exc)
        raise HTTPException(status_code=502, detail="Failed to fetch activity data")

    # Enrich system prompt with athlete profile and coaching memories
    profile_text = profile_to_text(get_profile_fields(mode), mode)
    if profile_text:
        system_prompt += f"\n\n{profile_text}"

    memories = get_all_memories()
    if memories:
        mem_lines = "\n".join(f"  [{m['category']}] {m['content']}" for m in memories)
        system_prompt += f"\n\n## Coaching Notes (remembered from previous sessions)\n{mem_lines}"

    def _run_llm():
        return backend.stateless_turn(system_prompt, user_content, on_token=lambda _: None)

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
