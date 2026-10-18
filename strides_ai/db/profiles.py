"""Profile CRUD operations.

The profile is one document stored as one ``profiles`` row per section
(``shared``, ``running``, ``cycling``, ``lifting``); see ``strides_ai/profile.py``.
"""

import json

import sqlalchemy as sa
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlmodel import Session

from ..body_metrics import normalize_personal
from ..profile import DISCIPLINE_KEYS, SECTIONS
from .models import Profile


def _load(session: Session, section: str) -> dict:
    row = session.get(Profile, section)
    return json.loads(row.fields_json) if row else {}


def get_fields(session: Session, mode: str | None = None) -> dict | None:
    """Return the unified profile document, or None if nothing has been saved.

    ``mode`` is accepted for call-site compatibility; the document is the same for every mode
    (the mode only decides how it is rendered).
    """
    shared = _load(session, "shared")
    disciplines = {name: _load(session, name) for name in DISCIPLINE_KEYS}
    if not shared and not any(disciplines.values()):
        return None
    if "personal" in shared:
        # Legacy free-text height/weight become height_cm/weight_kg here; the next save persists it.
        shared["personal"] = normalize_personal(shared["personal"])
    return {**shared, **{name: d for name, d in disciplines.items() if d}}


def get_updated(session: Session) -> dict[str, str | None]:
    """Last-modified timestamp for each section (None if never saved)."""
    out: dict[str, str | None] = {}
    for section in SECTIONS:
        row = session.get(Profile, section)
        out[section] = row.updated_at if row else None
    return out


def save_section(session: Session, section: str, data: dict) -> None:
    """Replace one section row. Other sections are untouched."""
    if section not in SECTIONS:
        raise ValueError(f"Unknown profile section: {section}")
    payload = json.dumps(data)
    stmt = sqlite_insert(Profile).values(mode=section, fields_json=payload)
    stmt = stmt.on_conflict_do_update(
        index_elements=["mode"],
        set_={"fields_json": payload, "updated_at": sa.text("datetime('now')")},
    )
    session.execute(stmt)
    session.commit()


def merge_section(session: Session, section: str, patch: dict) -> dict:
    """Shallow-merge ``patch`` into one section (nested dicts one level deep) and save it."""
    current = _load(session, section)
    for key, val in patch.items():
        if isinstance(val, dict) and isinstance(current.get(key), dict):
            current[key] = {**current[key], **val}
        else:
            current[key] = val
    save_section(session, section, current)
    return current


def get_max_hr(session: Session, default: int = 190) -> int:
    """Max heart rate from the profile, falling back to the legacy setting, then ``default``."""
    from . import settings as settings_crud

    val = _load(session, "shared").get("personal", {}).get("max_hr")
    if val not in (None, "") and str(val).strip().isdigit():
        return int(str(val).strip())
    legacy = settings_crud.get(session, "max_hr")
    return int(legacy) if legacy and legacy.isdigit() else default
