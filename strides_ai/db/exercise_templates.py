"""CRUD for cached HEVY exercise templates."""

import json

from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlmodel import Session, select

from .models import ExerciseTemplate


def upsert(session: Session, template: dict) -> None:
    """Insert or update a template row from a HEVY API payload."""
    secondary = template.get("secondary_muscle_groups")
    if isinstance(secondary, list):
        secondary_json = json.dumps(secondary)
    elif isinstance(secondary, str):
        secondary_json = secondary
    else:
        secondary_json = None

    is_custom = template.get("is_custom")
    if is_custom is not None:
        is_custom = 1 if bool(is_custom) else 0

    values = {
        "id": template["id"],
        "title": template.get("title"),
        "type": template.get("type"),
        "primary_muscle_group": template.get("primary_muscle_group"),
        "secondary_muscle_groups": secondary_json,
        "is_custom": is_custom,
    }
    stmt = sqlite_insert(ExerciseTemplate).values(**values)
    stmt = stmt.on_conflict_do_update(
        index_elements=["id"],
        set_={k: v for k, v in values.items() if k != "id"},
    )
    session.execute(stmt)


def get_all(session: Session) -> list[ExerciseTemplate]:
    return list(session.exec(select(ExerciseTemplate)).all())


def count(session: Session) -> int:
    return len(session.exec(select(ExerciseTemplate.id)).all())


def get_muscle_map(session: Session) -> dict[str, str]:
    """Return ``{template_id: primary_muscle_group}`` for non-null entries."""
    rows = session.exec(select(ExerciseTemplate.id, ExerciseTemplate.primary_muscle_group)).all()
    return {tid: muscle for tid, muscle in rows if muscle}
