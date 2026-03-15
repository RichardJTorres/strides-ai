"""Activities route."""

from fastapi import APIRouter, Depends
from sqlmodel import Session

from ...config import VALID_MODES
from ...db import activities as crud
from ...db.engine import get_session

router = APIRouter()


@router.get("/activities")
def get_activities(mode: str | None = None, session: Session = Depends(get_session)):
    if mode and mode in VALID_MODES:
        rows = crud.get_for_mode(session, mode)
    else:
        rows = crud.get_all(session)
    return [r.model_dump() for r in rows]
