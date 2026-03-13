"""Strava sync route."""

from fastapi import APIRouter, HTTPException, Request

from ...auth import get_access_token
from ...config import get_settings
from ...sync import sync_activities
from ..deps import init_backend

router = APIRouter()


@router.post("/sync")
def sync(request: Request, full: bool = False):
    settings = get_settings()
    if not settings.strava_client_id or not settings.strava_client_secret:
        raise HTTPException(status_code=500, detail="Strava credentials not configured")

    access_token = get_access_token(settings.strava_client_id, settings.strava_client_secret)
    new_count = sync_activities(access_token, full=full)
    if new_count > 0:
        init_backend(request.app)
    return {"new_activities": new_count}
