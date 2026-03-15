"""Profile CRUD operations."""

import json

import sqlalchemy as sa
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlmodel import Session

from .models import Profile


def get_fields(session: Session, mode: str) -> dict | None:
    """Return the profile fields dict for the given mode, or None if not saved."""
    row = session.get(Profile, mode)
    return json.loads(row.fields_json) if row else None


def save_fields(session: Session, mode: str, fields: dict) -> None:
    stmt = sqlite_insert(Profile).values(mode=mode, fields_json=json.dumps(fields))
    stmt = stmt.on_conflict_do_update(
        index_elements=["mode"],
        set_={"fields_json": json.dumps(fields), "updated_at": sa.text("datetime('now')")},
    )
    session.execute(stmt)
    session.commit()
