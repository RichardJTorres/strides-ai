"""Profile routes — one unified profile, edited section by section."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlmodel import Session

from ...db import calendar as calendar_crud
from ...db import profiles as crud
from ...db.engine import get_session
from ...profile import (
    DISCIPLINE_KEYS,
    DISCIPLINES,
    SECTIONS,
    disciplines_for_mode,
    get_default_section,
    profile_completeness,
    with_defaults,
)
from ..deps import init_backend

router = APIRouter()

Weekday = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _reject_null(v):
    """Omitting a key leaves it unchanged; sending null for an object or list is an error."""
    if v is None:
        raise ValueError("must not be null; omit the field to leave it unchanged")
    return v


class Personal(_Strict):
    name: str = ""
    gender: str = ""
    date_of_birth: str = ""
    height_cm: float | None = Field(default=None, gt=0, lt=300)
    weight_kg: float | None = Field(default=None, gt=0, lt=700)
    max_hr: int | None = Field(default=None, ge=60, le=250)
    body_notes: str | None = None


class Availability(_Strict):
    sessions_per_week: int | None = Field(default=None, ge=0, le=21)
    preferred_days: list[Weekday] = []
    long_session_day: Weekday | Literal[""] = ""
    notes: str = ""


class SharedSection(_Strict):
    personal: Personal | None = None
    goals: str | None = None
    availability: Availability | None = None
    injuries_and_health: str | None = None
    nutrition_snacks: list[str] | None = None
    other_notes: str | None = None
    coach_voice: str | None = None

    no_null = field_validator("personal", "availability", "nutrition_snacks", mode="before")(
        _reject_null
    )


class DisciplineSection(_Strict):
    since: str | None = None
    volume: str | None = None
    focus: str | None = None
    background: str | None = None
    bests: dict[str, str] | None = None
    gear: str | None = None

    no_null = field_validator("bests", mode="before")(_reject_null)


class SectionBody(BaseModel):
    fields: dict


def _validate(section: str, fields: dict) -> dict:
    """Validate a section body and return only the keys the caller supplied."""
    model = SharedSection if section == "shared" else DisciplineSection
    parsed = model.model_validate(fields)
    out = parsed.model_dump(exclude_unset=True)
    if section in DISCIPLINES and "bests" in out:
        allowed = {key for key, _ in DISCIPLINES[section].bests}
        unknown = set(out["bests"]) - allowed
        if unknown:
            raise ValueError(f"Unknown {section} bests: {', '.join(sorted(unknown))}")
    return out


@router.get("/profile")
def get_profile(
    request: Request,
    mode: str | None = None,
    session: Session = Depends(get_session),
):
    m = mode or request.app.state.mode
    stored = crud.get_fields(session, m)
    active = list(disciplines_for_mode(m))
    return {
        "fields": with_defaults(stored),
        "mode": m,
        "mode_sections": {
            "active": active,
            "other": [d for d in DISCIPLINE_KEYS if d not in active],
        },
        "completeness": profile_completeness(stored, m),
        "updated": crud.get_updated(session),
        "races": calendar_crud.get_prefs(session)["races"],
    }


@router.put("/profile/{section}")
def put_profile_section(
    section: str,
    request: Request,
    body: SectionBody,
    session: Session = Depends(get_session),
):
    """Merge the supplied keys into one section; keys not supplied are left as they were."""
    if section not in SECTIONS:
        raise HTTPException(status_code=404, detail=f"Unknown profile section: {section}")
    try:
        patch = _validate(section, body.fields)
    except ValueError as e:  # includes pydantic.ValidationError
        raise HTTPException(status_code=422, detail=str(e))
    merged = crud.merge_section(session, section, patch)
    init_backend(request.app)
    return {"status": "ok", "fields": merged}


@router.post("/profile/{section}/reset")
def reset_profile_section(
    section: str,
    request: Request,
    session: Session = Depends(get_session),
):
    if section not in SECTIONS:
        raise HTTPException(status_code=404, detail=f"Unknown profile section: {section}")
    defaults = get_default_section(section)
    if section == "shared":
        # Resetting the shared section never wipes the athlete's body measurements or voice.
        current = crud.get_fields(session) or {}
        defaults["personal"] = current.get("personal", defaults["personal"])
        defaults["coach_voice"] = current.get("coach_voice", "")
    crud.save_section(session, section, defaults)
    init_backend(request.app)
    return {"fields": defaults}
