"""Tests for the /calendar/compliance router — response shape, validation, and a cross-check
against calling strides_ai.compliance directly, guaranteeing no transcription drift between the
dataclass and the hand-built response dict. Calls the route handler function directly
(bypassing TestClient/app lifespan), the same convention tests/test_charts_router.py uses."""

from datetime import date, timedelta

import pytest
from fastapi import HTTPException
from sqlmodel import Session

from strides_ai import compliance, db
from strides_ai.api.routers.calendar import get_compliance
from strides_ai.db.engine import get_engine


def _call(start_date: str, end_date: str):
    with Session(get_engine()) as session:
        return get_compliance(start_date=start_date, end_date=end_date, session=session)


def test_invalid_date_raises_400(tmp_db):
    with pytest.raises(HTTPException) as exc_info:
        _call(start_date="not-a-date", end_date="2026-06-15")
    assert exc_info.value.status_code == 400


def test_start_after_end_raises_400(tmp_db):
    with pytest.raises(HTTPException) as exc_info:
        _call(start_date="2026-06-15", end_date="2026-06-01")
    assert exc_info.value.status_code == 400


def test_compliance_endpoint_shape(tmp_db, sample_activity):
    workout_date = sample_activity["start_date_local"][:10]
    db.save_planned_workout(workout_date, "Easy Run", None, 5.0, None, 30, "easy")
    db.upsert_activity(sample_activity)

    result = _call(start_date="2025-06-01", end_date="2025-06-30")
    assert set(result.keys()) == {"days", "summary"}
    assert len(result["days"]) == 1
    day = result["days"][0]
    assert set(day.keys()) == {
        "date",
        "workout_type",
        "status",
        "planned_distance_km",
        "actual_distance_km",
        "matched_activity_id",
        "note",
    }
    assert day["date"] == workout_date
    assert day["status"] == "completed"
    summary = result["summary"]
    assert set(summary.keys()) == {
        "total_scored",
        "completed",
        "modified",
        "missed",
        "unscored",
        "upcoming",
        "consistency_pct",
        "on_target_pct",
    }
    assert summary["completed"] == 1


def test_compliance_endpoint_no_plan_in_range_returns_empty_days(tmp_db):
    result = _call(start_date="2025-06-01", end_date="2025-06-30")
    assert result["days"] == []
    assert result["summary"]["total_scored"] == 0
    assert result["summary"]["consistency_pct"] is None


def test_compliance_endpoint_matches_compute_range_compliance_output(tmp_db, sample_activity):
    missed_date = (date.today() - timedelta(days=3)).isoformat()
    db.save_planned_workout(missed_date, "Easy Run", None, 5.0, None, 30, "easy")
    db.upsert_activity(sample_activity)  # unrelated date — won't match the planned workout

    start = (date.today() - timedelta(days=14)).isoformat()
    end = date.today().isoformat()
    result = _call(start_date=start, end_date=end)

    plan_rows = [{"date": missed_date, "workout_type": "Easy Run", "distance_km": 5.0}]
    planned = compliance.planned_workouts_from_rows(plan_rows)
    acts = compliance.compliance_activities_from_rows(
        [sample_activity_as_activity_row(sample_activity)]
    )
    expected_days = compliance.compute_range_compliance(planned, acts, date.today())
    expected_summary = compliance.summarize_compliance(expected_days)

    assert len(result["days"]) == len(expected_days)
    assert result["days"][0]["status"] == expected_days[0].status.value
    assert result["summary"]["missed"] == expected_summary.missed
    assert result["summary"]["completed"] == expected_summary.completed


def sample_activity_as_activity_row(sample_activity: dict) -> dict:
    """Mimic the shape db.upsert_activity + Activity.model_dump() produces for the fields
    compliance_activities_from_rows reads, without needing a second DB round-trip."""
    return {
        "id": sample_activity["id"],
        "date": sample_activity["start_date_local"][:10],
        "sport_type": sample_activity["sport_type"],
        "distance_m": sample_activity["distance"],
    }
