"""HEVY sync routes."""

from fastapi import APIRouter, HTTPException, Request

from ...config import get_settings
from ...hevy_sync import sync_hevy_workouts
from ..deps import init_backend

router = APIRouter()


@router.post("/hevy/sync")
def hevy_sync(request: Request, full: bool = False):
    settings = get_settings()
    if not settings.hevy_api_key:
        raise HTTPException(status_code=500, detail="HEVY_API_KEY not configured")

    new_count = sync_hevy_workouts(full=full)
    if new_count > 0:
        init_backend(request.app)
    return {"new_workouts": new_count}
