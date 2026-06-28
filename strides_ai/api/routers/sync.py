"""Sync routes — unified and per-source."""

from fastapi import APIRouter, HTTPException, Request

from ... import db
from ...sources import configured_sources, hevy_source, strava_source
from ...sources.base import ConfigurationError
from ..deps import init_backend

router = APIRouter()


@router.post("/sync")
def sync_all(request: Request, full: bool = False):
    """Sync all configured data sources and return aggregated counts."""
    sources = configured_sources()
    results = {s.source_name: s.sync(full=full) for s in sources}
    total = sum(results.values())
    if total > 0:
        init_backend(request.app)
    return {"total": total, "sources": results}


@router.post("/strava/sync")
def strava_sync(request: Request, full: bool = False):
    if not strava_source.is_configured():
        raise HTTPException(status_code=503, detail="Strava is not configured")
    new_count = strava_source.sync(full=full)
    if new_count > 0:
        init_backend(request.app)
    return {"new_activities": new_count}


@router.post("/hevy/sync")
def hevy_sync(request: Request, full: bool = False):
    if not hevy_source.is_configured():
        raise HTTPException(status_code=503, detail="HEVY is not configured")
    new_count = hevy_source.sync(full=full)
    if new_count > 0:
        init_backend(request.app)
    return {"new_workouts": new_count}


@router.post("/hevy/templates/sync")
def hevy_templates_sync():
    """Refresh the cached HEVY exercise-template catalogue (titles + muscle groups)."""
    if not hevy_source.is_configured():
        raise HTTPException(status_code=503, detail="HEVY is not configured")
    try:
        synced = hevy_source.sync_templates()
    except ConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return {"templates_synced": synced, "templates_total": db.get_exercise_template_count()}
