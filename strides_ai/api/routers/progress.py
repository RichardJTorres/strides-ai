"""Progress router: the plan streak, this week's quests and personal records."""

from datetime import date

from fastapi import APIRouter, Depends
from sqlmodel import Session

from ...db import activities as crud
from ...db import calendar as calendar_crud
from ...db.engine import get_session
from ...progress import ProgressPayload, build_progress
from ...units import UnitSystem
from ..deps import get_units

router = APIRouter()


@router.get("/progress", response_model=ProgressPayload)
def progress(
    session: Session = Depends(get_session), units: UnitSystem = Depends(get_units)
) -> ProgressPayload:
    """Computed on read from every planned workout and every activity. Not mode-scoped: the plan
    is shared across modes, and each record names its sport so the UI can filter."""
    plan_rows = [w.model_dump() for w in calendar_crud.get_plan(session)]
    activity_rows = [a.model_dump() for a in crud.get_all(session)]
    return build_progress(plan_rows, activity_rows, date.today(), units)
