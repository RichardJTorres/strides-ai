"""Tests for the exercise_templates DB CRUD."""

import json

from sqlmodel import Session

from strides_ai.db import exercise_templates as crud
from strides_ai.db.engine import get_engine


def _session(tmp_db) -> Session:
    return Session(get_engine())


def test_count_starts_at_zero(tmp_db):
    with _session(tmp_db) as s:
        assert crud.count(s) == 0


def test_upsert_inserts_row(tmp_db):
    with _session(tmp_db) as s:
        crud.upsert(
            s,
            {
                "id": "TPL1",
                "title": "Bench Press (Barbell)",
                "type": "weight_reps",
                "primary_muscle_group": "Chest",
                "secondary_muscle_groups": ["Triceps", "Shoulders"],
                "is_custom": False,
            },
        )
        s.commit()
        assert crud.count(s) == 1


def test_upsert_updates_existing_row(tmp_db):
    with _session(tmp_db) as s:
        crud.upsert(s, {"id": "TPL1", "primary_muscle_group": "Chest"})
        s.commit()
        crud.upsert(s, {"id": "TPL1", "primary_muscle_group": "Back"})
        s.commit()
        assert crud.count(s) == 1
        muscles = crud.get_muscle_map(s)
        assert muscles["TPL1"] == "Back"


def test_get_muscle_map_skips_null_muscles(tmp_db):
    with _session(tmp_db) as s:
        crud.upsert(s, {"id": "TPL_GOOD", "primary_muscle_group": "Chest"})
        crud.upsert(s, {"id": "TPL_NULL", "primary_muscle_group": None})
        s.commit()
        muscles = crud.get_muscle_map(s)
        assert muscles == {"TPL_GOOD": "Chest"}


def test_upsert_serialises_secondary_muscle_list(tmp_db):
    with _session(tmp_db) as s:
        crud.upsert(
            s,
            {
                "id": "TPL1",
                "primary_muscle_group": "Chest",
                "secondary_muscle_groups": ["Triceps", "Shoulders"],
            },
        )
        s.commit()
        rows = crud.get_all(s)
        assert json.loads(rows[0].secondary_muscle_groups) == ["Triceps", "Shoulders"]


def test_upsert_handles_missing_optional_fields(tmp_db):
    with _session(tmp_db) as s:
        crud.upsert(s, {"id": "TPL1"})
        s.commit()
        rows = crud.get_all(s)
        assert rows[0].id == "TPL1"
        assert rows[0].title is None
        assert rows[0].primary_muscle_group is None
