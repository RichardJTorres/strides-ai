"""Sync routes — unified and per-source."""

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request

from ... import db
from ...sources import configured_sources, hevy_source, strava_source
from ...sources.base import AuthError, ConfigurationError
from ..deps import init_backend

router = APIRouter()


def _mark_synced() -> None:
    db.set_setting("last_sync_at", datetime.now(timezone.utc).isoformat())


@router.post("/sync")
def sync_all(request: Request, full: bool = False):
    """Sync all configured data sources and return aggregated counts."""
    sources = configured_sources()
    results = {s.source_name: s.sync(full=full) for s in sources}
    total = sum(results.values())
    if total > 0:
        init_backend(request.app)
    _mark_synced()
    return {"total": total, "sources": results}


@router.post("/strava/sync")
def strava_sync(request: Request, full: bool = False):
    if not strava_source.is_configured():
        raise HTTPException(status_code=503, detail="Strava is not configured")
    new_count = strava_source.sync(full=full)
    if new_count > 0:
        init_backend(request.app)
    _mark_synced()
    return {"new_activities": new_count}


@router.post("/strava/reanalyze")
def strava_reanalyze(request: Request, restart: bool = False):
    """Recompute activity metrics; ``restart`` requeues every analysed activity first."""
    if not strava_source.is_configured():
        raise HTTPException(status_code=503, detail="Strava is not configured")
    try:
        result = strava_source.reanalyze(restart=restart)
    except AuthError as exc:
        # Activities already queued stay pending; "Continue" picks them up once auth works.
        raise HTTPException(
            status_code=503, detail=f"{exc}. Check your Strava connection and try again."
        )
    if result["analyzed"] > 0:
        init_backend(request.app)
    return result


@router.post("/hevy/sync")
def hevy_sync(request: Request, full: bool = False):
    if not hevy_source.is_configured():
        raise HTTPException(status_code=503, detail="HEVY is not configured")
    new_count = hevy_source.sync(full=full)
    if new_count > 0:
        init_backend(request.app)
    _mark_synced()
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
