"""Profile CRUD operations."""

import json

import sqlalchemy as sa
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlmodel import Session

from .models import Profile


def get_fields(session: Session, mode: str) -> dict | None:
    """Return the profile fields dict for the given mode merged with shared personal data.

    Personal info (name, gender, etc.) is stored once under mode="personal" and merged
    into every mode's fields so the athlete only needs to fill it in once.
    """
    personal_row = session.get(Profile, "personal")
    mode_row = session.get(Profile, mode)
    personal = json.loads(personal_row.fields_json) if personal_row else {}
    mode_data = json.loads(mode_row.fields_json) if mode_row else {}
    if not personal and not mode_data:
        return None
    return {**mode_data, "personal": personal}


def save_fields(session: Session, mode: str, fields: dict) -> None:
    """Save profile fields, storing personal data shared across all modes separately."""
    personal = fields.get("personal", {})
    mode_data = {k: v for k, v in fields.items() if k != "personal"}
    for row_mode, data in [("personal", personal), (mode, mode_data)]:
        stmt = sqlite_insert(Profile).values(mode=row_mode, fields_json=json.dumps(data))
        stmt = stmt.on_conflict_do_update(
            index_elements=["mode"],
            set_={"fields_json": json.dumps(data), "updated_at": sa.text("datetime('now')")},
        )
        session.execute(stmt)
    session.commit()
