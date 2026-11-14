"""Usage router: tokens and estimated cost of every LLM call, from the usage log."""

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from ...db import usage as usage_log
from ...db.engine import get_session

router = APIRouter()


@router.get("/usage")
def usage(days: int = Query(30, ge=1, le=365), session: Session = Depends(get_session)):
    """Totals plus per-day, per-model and per-source breakdowns. Never calls an LLM. Costs are
    estimates; ``unpriced_calls`` counts calls whose cost could not be estimated."""
    return usage_log.summarize(session, days)
