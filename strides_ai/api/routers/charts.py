"""Charts route."""

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from ...analytics.composition import get_chart_datasets
from ...charts_lifting import get_chart_data as get_lifting_chart_data
from ...config import VALID_MODES
from ...db import activities as crud
from ...db import exercise_templates as tmpl_crud
from ...db.engine import get_session
from ...units import UnitSystem
from ..deps import get_units

router = APIRouter()


@router.get("/charts")
def charts(
    unit: str | None = None,
    mode: str = "running",
    session: Session = Depends(get_session),
    units: UnitSystem = Depends(get_units),
):
    # The unit system setting drives charts; an explicit ?unit= still overrides it.
    if unit is None:
        unit = "miles" if units is UnitSystem.IMPERIAL else "km"
    if unit not in ("miles", "km"):
        raise HTTPException(status_code=400, detail="unit must be 'miles' or 'km'")
    if mode not in VALID_MODES:
        mode = "running"
    rows = [r.model_dump() for r in crud.get_for_mode(session, mode)]
    if mode == "lifting":
        # Unchanged — the typed analytics envelope below is cardio-only.
        muscle_map = tmpl_crud.get_muscle_map(session)
        return get_lifting_chart_data(rows, template_muscle_map=muscle_map)
    return {"mode": mode, "unit": unit, "charts": get_chart_datasets(rows, mode, unit)}
