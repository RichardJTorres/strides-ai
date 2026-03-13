"""Activities route."""

from fastapi import APIRouter

from ... import db
from ...config import VALID_MODES

router = APIRouter()


@router.get("/activities")
def activities(mode: str | None = None):
    if mode and mode in VALID_MODES:
        rows = db.get_activities_for_mode(mode)
    else:
        rows = db.get_all_activities()
    return [dict(r) for r in rows]
