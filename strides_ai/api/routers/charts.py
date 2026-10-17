"""Charts routes."""

import asyncio
import json
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from ...analytics.composition import get_chart_datasets
from ...charts_lifting import get_chart_data as get_lifting_chart_data
from ...config import VALID_MODES
from ...db import activities as crud
from ...db import calendar as calendar_crud
from ...db import exercise_templates as tmpl_crud
from ...db import settings as settings_crud
from ...db.engine import get_session
from ...insights import (
    INSIGHTS_SYSTEM_PROMPT,
    build_digest,
    build_insights_prompt,
    digest_fingerprint,
    parse_insights_response,
)
from ...units import UnitSystem
from ..deps import get_backend, get_units

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


def _insights_key(mode: str, units: UnitSystem) -> str:
    return f"charts_insights:{mode}:{units.value}"


def _insights_inputs(session: Session, mode: str, units: UnitSystem):
    if mode not in VALID_MODES or mode == "lifting":
        raise HTTPException(status_code=400, detail="Insights are available for cardio modes only")
    today = date.today()
    rows = [r.model_dump() for r in crud.get_for_mode(session, mode)]
    plan_rows = [w.model_dump() for w in calendar_crud.get_plan(session)]
    races = calendar_crud.get_prefs(session).get("races", [])
    digest = build_digest(rows, mode, units, today, plan_rows=plan_rows, races=races)
    return digest, digest_fingerprint(rows, mode, units, today)


def _load_cached_insights(session: Session, mode: str, units: UnitSystem) -> dict | None:
    raw = settings_crud.get(session, _insights_key(mode, units))
    try:
        return json.loads(raw) if raw else None
    except json.JSONDecodeError:
        return None


def _insights_payload(
    mode: str, units: UnitSystem, digest: dict, fingerprint: str, cached: dict | None
) -> dict:
    return {
        "mode": mode,
        "unit_system": units.value,
        "digest": digest,
        "report": cached["report"] if cached else None,
        "generated_at": cached["generated_at"] if cached else None,
        "model": cached["model"] if cached else None,
        "stale": bool(cached and cached["fingerprint"] != fingerprint),
    }


@router.get("/charts/insights")
def get_insights(
    mode: str = "running",
    session: Session = Depends(get_session),
    units: UnitSystem = Depends(get_units),
):
    """Current digest plus the cached LLM readout (if any). Never calls the LLM."""
    digest, fingerprint = _insights_inputs(session, mode, units)
    cached = _load_cached_insights(session, mode, units)
    return _insights_payload(mode, units, digest, fingerprint, cached)


@router.post("/charts/insights")
async def generate_insights(
    mode: str = "running",
    force: bool = False,
    session: Session = Depends(get_session),
    backend=Depends(get_backend),
    units: UnitSystem = Depends(get_units),
):
    """Generate (or return the still-fresh cached) LLM readout of the training digest."""
    digest, fingerprint = _insights_inputs(session, mode, units)
    cached = _load_cached_insights(session, mode, units)
    if not digest["sufficient"]:
        return _insights_payload(mode, units, digest, fingerprint, None)
    if cached and not force and cached["fingerprint"] == fingerprint:
        return _insights_payload(mode, units, digest, fingerprint, cached)

    prompt = build_insights_prompt(digest, units)

    def _run_llm() -> str:
        return backend.stateless_turn(INSIGHTS_SYSTEM_PROMPT, prompt, lambda _: None)

    try:
        text = await asyncio.get_event_loop().run_in_executor(None, _run_llm)
        report = parse_insights_response(text, digest)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=502, detail=f"Model returned invalid JSON: {exc}")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    cached = {
        "report": report,
        "fingerprint": fingerprint,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": backend.label,
    }
    settings_crud.set(session, _insights_key(mode, units), json.dumps(cached))
    return _insights_payload(mode, units, digest, fingerprint, cached)
