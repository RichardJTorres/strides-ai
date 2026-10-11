"""Tests for the /charts router — API contract shape, validation, and the lifting non-regression
guarantee. Calls the route handler function directly (bypassing TestClient/app lifespan, which
isn't needed here and isn't used anywhere else in this test suite) with an explicit session,
since FastAPI's Depends() defaults are just ignored when a value is passed directly."""

from fastapi import HTTPException
from sqlmodel import Session

import pytest

from strides_ai import db
from strides_ai.api.routers.charts import charts
from strides_ai.db.engine import get_engine


def _call(unit="miles", mode="running"):
    with Session(get_engine()) as session:
        return charts(unit=unit, mode=mode, session=session)


def test_invalid_unit_raises_400(tmp_db):
    with pytest.raises(HTTPException) as exc_info:
        _call(unit="furlongs")
    assert exc_info.value.status_code == 400


def test_invalid_mode_falls_back_to_running(tmp_db):
    result = _call(mode="not-a-real-mode")
    assert result["mode"] == "running"


def test_cardio_response_envelope_shape(tmp_db):
    result = _call(mode="running")
    assert set(result.keys()) == {"mode", "unit", "charts"}
    assert result["mode"] == "running"
    assert result["unit"] == "miles"
    assert isinstance(result["charts"], list)


def test_cardio_response_charts_are_ordered_and_typed(tmp_db):
    result = _call(mode="running")
    ids = [c.id for c in result["charts"]]
    assert ids[0] == "weekly_distance"
    assert ids[1] == "atl_ctl"
    assert all(hasattr(c, "chart_type") for c in result["charts"])


def test_hybrid_response_includes_sport_specific_charts(tmp_db):
    result = _call(mode="hybrid")
    ids = [c.id for c in result["charts"]]
    assert "run_aerobic_efficiency" in ids
    assert "ride_aerobic_efficiency" in ids
    assert "training_time_allocation" in ids


def test_lifting_response_shape_is_unchanged(tmp_db):
    """The typed cardio envelope must not leak into the lifting path at all."""
    result = _call(mode="lifting")
    assert set(result.keys()) == {
        "weekly_volume",
        "one_rm_progression",
        "muscle_group_sets",
        "weekly_sessions",
        "rpe_trend",
    }
    assert "charts" not in result
    assert "mode" not in result


def test_cycling_datasets_identify_their_sport(tmp_db):
    result = _call(mode="cycling")
    assert all(c.sport == "ride" for c in result["charts"])
