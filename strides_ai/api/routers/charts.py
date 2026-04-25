"""Charts route."""

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from ...charts_data import get_chart_data as get_cardio_chart_data
from ...charts_lifting import get_chart_data as get_lifting_chart_data
from ...config import VALID_MODES
from ...db import activities as crud
from ...db import exercise_templates as tmpl_crud
from ...db.engine import get_session

router = APIRouter()


@router.get("/charts")
def charts(
    unit: str = "miles",
    mode: str = "running",
    session: Session = Depends(get_session),
):
    if unit not in ("miles", "km"):
        raise HTTPException(status_code=400, detail="unit must be 'miles' or 'km'")
    if mode not in VALID_MODES:
        mode = "running"
    rows = [r.model_dump() for r in crud.get_for_mode(session, mode)]
    if mode == "lifting":
        muscle_map = tmpl_crud.get_muscle_map(session)
        return get_lifting_chart_data(rows, template_muscle_map=muscle_map)
    return get_cardio_chart_data(rows, unit)
