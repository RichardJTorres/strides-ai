"""Strava sync route."""

from fastapi import APIRouter, HTTPException, Request

from ...sources import strava_source
from ...sources.base import ConfigurationError
from ..deps import init_backend

router = APIRouter()


@router.post("/strava/sync")
def sync(request: Request, full: bool = False):
    try:
        new_count = strava_source.sync(full=full)
    except ConfigurationError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    if new_count > 0:
        init_backend(request.app)
    return {"new_activities": new_count}
