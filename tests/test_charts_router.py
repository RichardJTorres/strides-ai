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
    assert ids[0] == "atl_ctl"
    assert ids[1] == "weekly_distance"
    assert all(hasattr(c, "chart_type") for c in result["charts"])


def test_hybrid_response_includes_sport_specific_charts(tmp_db):
    result = _call(mode="hybrid")
    ids = [c.id for c in result["charts"]]
    assert "run_aerobic_efficiency" in ids
    assert "ride_aerobic_efficiency" in ids
    assert "training_time_allocation" in ids
    assert "run_climbing_ratio" in ids
    assert "ride_climbing_ratio" in ids


def test_running_and_cycling_responses_include_climbing_ratio(tmp_db):
    assert "climbing_ratio" in [c.id for c in _call(mode="running")["charts"]]
    assert "climbing_ratio" in [c.id for c in _call(mode="cycling")["charts"]]


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


# ── /charts/insights ─────────────────────────────────────────────────────────────

import asyncio
import json
from datetime import date, timedelta

from strides_ai.api.routers.charts import generate_insights, get_insights
from strides_ai.units import UnitSystem

_GOOD_REPORT = {
    "status": "building",
    "headline": "Volume is up.",
    "findings": [{"title": "Volume up", "detail": "d", "tone": "positive", "metric_ids": []}],
    "recommendations": [{"action": "Hold volume", "why": "consolidate", "metric_ids": []}],
}


class _StubBackend:
    label = "stub-model"

    def __init__(self, reply=None):
        self.reply = json.dumps(_GOOD_REPORT) if reply is None else reply
        self.calls = 0

    def stateless_turn(self, system, user_input, on_token):
        self.calls += 1
        return self.reply


def _seed_activities(start_id=1, weeks=6, last_day=None):
    last_day = last_day or date.today() - timedelta(days=8)
    d, i = last_day - timedelta(weeks=weeks), start_id
    while d <= last_day:
        db.upsert_activity(
            {
                "id": i,
                "name": "Run",
                "start_date_local": f"{d.isoformat()}T07:00:00Z",
                "distance": 10_000.0,
                "moving_time": 3600,
                "elapsed_time": 3700,
                "total_elevation_gain": 50.0,
                "sport_type": "Run",
            }
        )
        d += timedelta(days=2)
        i += 1
    return i


def _get(mode="running"):
    with Session(get_engine()) as session:
        return get_insights(mode=mode, session=session, units=UnitSystem.METRIC)


def _post(backend, mode="running", force=False):
    with Session(get_engine()) as session:
        return asyncio.run(
            generate_insights(
                mode=mode, force=force, session=session, backend=backend, units=UnitSystem.METRIC
            )
        )


def test_insights_lifting_is_400(tmp_db):
    with pytest.raises(HTTPException) as exc:
        _get(mode="lifting")
    assert exc.value.status_code == 400


def test_insights_get_without_cache(tmp_db):
    _seed_activities()
    result = _get()
    assert result["report"] is None and result["stale"] is False
    assert result["digest"]["sufficient"] is True


def test_insights_insufficient_data_skips_llm(tmp_db):
    backend = _StubBackend()
    result = _post(backend)
    assert backend.calls == 0
    assert result["report"] is None and result["digest"]["sufficient"] is False


def test_insights_post_generates_caches_and_goes_stale(tmp_db):
    next_id = _seed_activities()
    backend = _StubBackend()
    first = _post(backend)
    assert first["report"]["status"] == "building" and first["model"] == "stub-model"
    assert backend.calls == 1

    _post(backend)  # fresh cache: no second LLM call
    assert backend.calls == 1
    assert _get()["stale"] is False

    _post(backend, force=True)
    assert backend.calls == 2

    db.upsert_activity(
        {
            "id": next_id,
            "name": "New",
            "start_date_local": f"{date.today().isoformat()}T07:00:00Z",
            "distance": 5000.0,
            "moving_time": 1800,
            "elapsed_time": 1800,
            "total_elevation_gain": 10.0,
            "sport_type": "Run",
        }
    )
    stale = _get()
    assert stale["stale"] is True and stale["report"] is not None
    _post(backend)  # stale cache regenerates without force
    assert backend.calls == 3


def test_insights_bad_json_is_502(tmp_db):
    _seed_activities()
    with pytest.raises(HTTPException) as exc:
        _post(_StubBackend(reply="not json"))
    assert exc.value.status_code == 502
