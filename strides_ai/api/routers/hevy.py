"""HEVY sync routes."""

from fastapi import APIRouter, HTTPException, Request

from ...sources import hevy_source
from ...sources.base import ConfigurationError
from ..deps import init_backend

router = APIRouter()


@router.post("/hevy/sync")
def hevy_sync(request: Request, full: bool = False):
    try:
        new_count = hevy_source.sync(full=full)
    except ConfigurationError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    if new_count > 0:
        init_backend(request.app)
    return {"new_workouts": new_count}
