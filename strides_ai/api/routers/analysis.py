"""Deep-dive analysis endpoint."""

import asyncio
import functools
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from ... import db
from ...analysis import (
    DEEP_DIVE_SYSTEM_PROMPT,
    RateLimitError,
    condense_streams_for_deep_dive,
    fetch_activity_streams,
)
from ...auth import get_access_token
from ..deps import get_backend

router = APIRouter()
log = logging.getLogger(__name__)


class DeepDiveResponse(BaseModel):
    activity_id: int
    report: str
    cached: bool
    completed_at: str | None


@router.post("/activities/{activity_id}/deep-dive", response_model=DeepDiveResponse)
async def deep_dive(
    activity_id: int,
    request: Request,
    force: bool = False,
    backend=Depends(get_backend),
) -> DeepDiveResponse:
    """
    Generate (or return cached) a deep-dive LLM analysis for a single activity.

    Set force=true to regenerate even if a cached report exists.
    """
    activity = db.get_activity(activity_id)
    if activity is None:
        raise HTTPException(status_code=404, detail="Activity not found")

    # Return cached report unless force=true
    if activity.get("deep_dive_report") and not force:
        return DeepDiveResponse(
            activity_id=activity_id,
            report=activity["deep_dive_report"],
            cached=True,
            completed_at=activity.get("deep_dive_completed_at"),
        )

    # Fetch streams
    try:
        access_token = get_access_token()
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

    # Build condensed stream representation
    condensed = condense_streams_for_deep_dive(streams, activity)

    # Run the (sync) LLM call in a thread pool so we don't block the event loop
    def _run_llm():
        text, _ = backend.stream_turn(
            DEEP_DIVE_SYSTEM_PROMPT,
            condensed,
            on_token=lambda _: None,
        )
        return text

    try:
        report = await asyncio.get_event_loop().run_in_executor(None, _run_llm)
    except Exception as exc:
        log.error("LLM deep dive failed for activity %s: %s", activity_id, exc)
        raise HTTPException(status_code=500, detail="LLM analysis failed")

    completed_at = datetime.now(timezone.utc).isoformat()
    db.save_analysis(
        activity_id,
        {"deep_dive_report": report, "deep_dive_completed_at": completed_at},
    )

    return DeepDiveResponse(
        activity_id=activity_id,
        report=report,
        cached=False,
        completed_at=completed_at,
    )
