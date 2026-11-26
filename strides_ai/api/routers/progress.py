"""Progress router: the plan streak, personal records and the monthly progression."""

from datetime import date

from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from ...db import activities as crud
from ...db import calendar as calendar_crud
from ...db.engine import get_session
from ...progress import (
    DEFAULT_PROGRESSION_MONTHS,
    MAX_PROGRESSION_MONTHS,
    Progression,
    ProgressPayload,
    build_progress,
    monthly_progression,
)
from ...units import UnitSystem
from ..deps import get_units

router = APIRouter()


@router.get("/progress", response_model=ProgressPayload)
def progress(
    session: Session = Depends(get_session), units: UnitSystem = Depends(get_units)
) -> ProgressPayload:
    """Computed on read from every planned workout and every activity. Not mode-scoped: the plan
    is shared across modes, and each record names its sport so the UI can filter."""
    plan_rows = calendar_crud.get_plan_rows(session)
    activity_rows = [a.model_dump() for a in crud.get_all(session)]
    return build_progress(plan_rows, activity_rows, date.today(), units)


@router.get("/progress/months", response_model=Progression)
def progress_months(
    sport: Literal["run", "ride"],
    months: int = Query(DEFAULT_PROGRESSION_MONTHS, ge=1, le=MAX_PROGRESSION_MONTHS),
    session: Session = Depends(get_session),
) -> Progression:
    """Month by month volume and peaks for one sport, in SI; the same series the coach's
    get_progression tool reads, so a chart and the chat show the same numbers."""
    rows = [
        a.model_dump(exclude={"raw_json", "exercises_json", "deep_dive_report"})
        for a in crud.get_all(session)
    ]
    return monthly_progression(rows, sport, months, date.today())
