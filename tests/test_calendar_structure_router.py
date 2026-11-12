"""Structured-workout routes: GET plan exposes parsed structure, /zwo downloads a .zwo.
Calls handlers directly (no TestClient), like tests/test_calendar_compliance_router.py."""

import xml.etree.ElementTree as ET

import pytest
from fastapi import HTTPException
from sqlmodel import Session

from tests.plan_helpers import save_planned_workout, save_races
from strides_ai import db
from strides_ai.api.routers.calendar import download_zwo, get_calendar_entries
from strides_ai.db.engine import get_engine

STRUCT = {
    "blocks": [
        {"kind": "warmup", "duration_s": 600, "from_pct": 0.5, "to_pct": 0.75},
        {"kind": "steady", "duration_s": 1200, "pct": 0.85},
    ]
}


def _id(date):
    return db.get_training_plan(date, date)[0]["id"]


def test_get_plan_exposes_parsed_structure(tmp_db):
    save_planned_workout("2026-10-02", "Indoor Ride", None, 30, 450, 40, "hard", structure=STRUCT)
    save_planned_workout("2026-10-03", "Easy Run", None, 5, None, 30, "easy")
    with Session(get_engine()) as session:
        rows = {r["date"]: r for r in get_calendar_entries(session=session)}
    assert rows["2026-10-02"]["structure"] == STRUCT
    assert "structure_json" not in rows["2026-10-02"]
    assert rows["2026-10-03"]["structure"] is None


def test_zwo_download(tmp_db):
    save_planned_workout(
        "2026-10-02", "Indoor Ride", "Sweet spot", 30, 450, 40, "hard", structure=STRUCT
    )
    with Session(get_engine()) as session:
        resp = download_zwo(_id("2026-10-02"), session=session)
    assert resp.media_type == "application/xml"
    assert 'filename="2026-10-02-indoor-ride-2026-10-02.zwo"' in resp.headers["content-disposition"]
    root = ET.fromstring(resp.body)
    assert [e.tag for e in root.find("workout")] == ["Warmup", "SteadyState"]
    assert root.findtext("description") == "Sweet spot"


def test_zwo_404_without_structure(tmp_db):
    save_planned_workout("2026-10-02", "Indoor Ride", None, 30, 450, 40, "hard")
    with Session(get_engine()) as session:
        with pytest.raises(HTTPException) as exc:
            download_zwo(_id("2026-10-02"), session=session)
        assert exc.value.status_code == 404
        with pytest.raises(HTTPException) as exc:
            download_zwo(99999, session=session)
        assert exc.value.status_code == 404
