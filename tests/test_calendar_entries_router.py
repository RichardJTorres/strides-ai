"""Entry routes: create / patch / delete / bulk, calling handlers directly."""

import pytest
from fastapi import HTTPException
from sqlmodel import Session

from strides_ai import db
from strides_ai.api.routers.calendar import (
    BulkBody,
    ChangeOp,
    EntryBody,
    bulk_calendar_entries,
    create_calendar_entry,
    delete_calendar_entry,
    get_calendar_entries,
    get_kinds,
    patch_calendar_entry,
)
from strides_ai.db.engine import get_engine

DAY = "2026-10-10"


def _session():
    return Session(get_engine())


def test_kinds_endpoint_serves_the_taxonomy():
    out = get_kinds()
    assert "race" in out["kinds"] and "Easy Run" in out["workout_types"]["run"]
    assert "Running Race" not in out["workout_types"]["run"]


def test_create_resolves_legacy_race_type_and_description(tmp_db):
    with _session() as s:
        made = create_calendar_entry(
            EntryBody(date=DAY, workout_type="Running Race", description="Fall 10K"), session=s
        )
    assert made["kind"] == "race" and made["title"] == "Fall 10K" and made["sport"] == "run"


def test_patch_applies_only_sent_fields_and_null_clears(tmp_db):
    with _session() as s:
        made = create_calendar_entry(
            EntryBody(date=DAY, kind="workout", workout_type="Easy Run", distance_km=5), session=s
        )
        out = patch_calendar_entry(made["id"], EntryBody(duration_min=40), session=s)
        assert out["distance_km"] == 5 and out["duration_min"] == 40
        out = patch_calendar_entry(made["id"], EntryBody(distance_km=None), session=s)
        assert out["distance_km"] is None and out["duration_min"] == 40


def test_patch_missing_entry_is_404_and_bad_write_is_400(tmp_db):
    with _session() as s:
        with pytest.raises(HTTPException) as exc:
            patch_calendar_entry(999, EntryBody(duration_min=1), session=s)
        assert exc.value.status_code == 404
        with pytest.raises(HTTPException) as exc:
            create_calendar_entry(EntryBody(date=DAY, kind="travel", distance_km=5), session=s)
        assert exc.value.status_code == 400


def test_drag_is_a_date_only_patch_and_coexists_with_the_target_day(tmp_db):
    with _session() as s:
        a = create_calendar_entry(
            EntryBody(date=DAY, kind="workout", workout_type="Easy Run"), session=s
        )
        create_calendar_entry(EntryBody(date="2026-10-11", kind="rest"), session=s)
        moved = patch_calendar_entry(a["id"], EntryBody(date="2026-10-11"), session=s)
        assert moved["date"] == "2026-10-11"
        rows = get_calendar_entries(start_date="2026-10-11", end_date="2026-10-11", session=s)
        assert sorted(r["kind"] for r in rows) == ["rest", "workout"]


def test_bulk_is_atomic_and_retry_safe(tmp_db):
    ok = BulkBody(
        request_id="r1",
        ops=[
            ChangeOp(op="create", date=DAY, workout_type="Easy Run"),
            ChangeOp(op="create", date=DAY, workout_type="Rest"),
        ],
    )
    with _session() as s:
        first = bulk_calendar_entries(ok, session=s)
        again = bulk_calendar_entries(ok, session=s)
        assert first["created"] == again["created"] and len(db.get_training_plan()) == 2
        bad = BulkBody(
            ops=[
                ChangeOp(op="delete", id=first["created"][0]),
                ChangeOp(op="create", date="nope", workout_type="Easy Run"),
            ]
        )
        with pytest.raises(HTTPException) as exc:
            bulk_calendar_entries(bad, session=s)
        assert exc.value.status_code == 400
    assert len(db.get_training_plan()) == 2  # the delete rolled back with the failure


def test_delete_entry(tmp_db):
    with _session() as s:
        made = create_calendar_entry(EntryBody(date=DAY, kind="rest"), session=s)
        delete_calendar_entry(made["id"], session=s)
        assert get_calendar_entries(session=s) == []


def test_patch_with_a_different_kind_is_refused(tmp_db):
    with _session() as s:
        made = create_calendar_entry(
            EntryBody(date=DAY, kind="workout", workout_type="Easy Run"), session=s
        )
        with pytest.raises(HTTPException) as exc:
            patch_calendar_entry(made["id"], EntryBody(kind="race"), session=s)
        assert exc.value.status_code == 400
