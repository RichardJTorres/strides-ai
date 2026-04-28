"""Charts route."""

from fastapi import APIRouter, Depends
from sqlmodel import Session

from ...charts_data import get_chart_data as get_cardio_chart_data
from ...charts_lifting import get_chart_data as get_lifting_chart_data
from ...config import VALID_MODES
from ...db import activities as crud
from ...db import exercise_templates as tmpl_crud
from ...db import settings as settings_crud
from ...db.engine import get_session

router = APIRouter()


@router.get("/charts")
def charts(
    mode: str = "running",
    session: Session = Depends(get_session),
):
    """Return chart data for the requested mode in the user's preferred units.

    The legacy ``?unit=miles|km`` query parameter is no longer honoured —
    units are read from the global ``units`` setting (``metric`` | ``imperial``).
    """
    if mode not in VALID_MODES:
        mode = "running"
    units = settings_crud.get(session, "units", "metric") or "metric"
    rows = [r.model_dump() for r in crud.get_for_mode(session, mode)]
    if mode == "lifting":
        muscle_map = tmpl_crud.get_muscle_map(session)
        return get_lifting_chart_data(rows, template_muscle_map=muscle_map, units=units)
    # charts_data.py internally speaks "miles"|"km"; translate.
    cardio_unit = "miles" if units == "imperial" else "km"
    return get_cardio_chart_data(rows, cardio_unit)
