"""Charts route."""

from fastapi import APIRouter, HTTPException

from ... import db
from ...charts_data import get_chart_data
from ...config import VALID_MODES

router = APIRouter()


@router.get("/charts")
def charts(unit: str = "miles", mode: str = "running"):
    if unit not in ("miles", "km"):
        raise HTTPException(status_code=400, detail="unit must be 'miles' or 'km'")
    if mode not in VALID_MODES:
        mode = "running"
    rows = db.get_activities_for_mode(mode)
    return get_chart_data(rows, unit)
