"""Activities route."""

from fastapi import APIRouter, Depends
from sqlmodel import Session

from ...analysis import render_analysis_summary
from ...config import VALID_MODES
from ...db import activities as crud
from ...db.engine import get_session
from ...units import UnitSystem
from ..deps import get_units

router = APIRouter()


@router.get("/activities")
def get_activities(
    mode: str | None = None,
    session: Session = Depends(get_session),
    units: UnitSystem = Depends(get_units),
):
    if mode and mode in VALID_MODES:
        rows = crud.get_for_mode(session, mode)
    else:
        rows = crud.get_all(session)
    # Measurements stay SI (the UI converts); only the prose summary is rendered server-side.
    result = []
    for r in rows:
        row = r.model_dump()
        row["analysis_summary"] = render_analysis_summary(row, units)
        result.append(row)
    return result
