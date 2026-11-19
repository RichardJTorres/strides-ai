"""Reanalysing activities after an input their metrics depend on (max HR) changes."""

import sqlalchemy as sa

from strides_ai import db, sync
from strides_ai.db.engine import get_engine


def _activity(sample, activity_id, status, source=None):
    db.upsert_activity({**sample, "id": activity_id})
    db.save_analysis(activity_id, {"analysis_status": status})
    if source:
        with get_engine().begin() as conn:
            conn.execute(
                sa.text("UPDATE activities SET source = :s WHERE id = :i"),
                {"s": source, "i": activity_id},
            )


def _status(activity_id):
    return db.get_activity(activity_id)["analysis_status"]


def test_mark_for_reanalysis_queues_analysed_strava_rows_only(tmp_db, sample_activity):
    _activity(sample_activity, 1, "done")
    _activity(sample_activity, 2, "error", source="strava")
    _activity(sample_activity, 3, "skipped")  # no stream data: refetching cannot help
    _activity(sample_activity, 4, "done", source="hevy")  # not Strava-analysed

    assert db.mark_for_reanalysis() == 2
    assert [_status(i) for i in (1, 2, 3, 4)] == ["pending", "pending", "skipped", "done"]
    assert db.count_pending_analysis() == 2


def test_reanalyze_restart_processes_everything_with_current_max_hr(
    tmp_db, sample_activity, monkeypatch
):
    for i in (1, 2, 3):
        _activity(sample_activity, i, "done")
    monkeypatch.setattr(db, "get_max_hr", lambda: 172)
    seen = []

    def fake_analyze(act, token, max_hr, renormalize):
        seen.append((act["id"], max_hr))
        db.save_analysis(act["id"], {"analysis_status": "done"})
        return "done"

    monkeypatch.setattr(sync, "analyze_activity", fake_analyze)
    result = sync.reanalyze("token", restart=True)

    assert sorted(seen) == [(1, 172), (2, 172), (3, 172)]
    assert result == {"queued": 3, "analyzed": 3, "remaining": 0, "rate_limited": False}


def test_rate_limit_stops_and_continue_does_not_requeue(tmp_db, sample_activity, monkeypatch):
    for i in (1, 2, 3):
        _activity(sample_activity, i, "done")
    budget = {"left": 1}

    def fake_analyze(act, token, max_hr, renormalize):
        if budget["left"] == 0:
            db.save_analysis(act["id"], {"analysis_status": "pending"})
            return "pending"
        budget["left"] -= 1
        db.save_analysis(act["id"], {"analysis_status": "done"})
        return "done"

    monkeypatch.setattr(sync, "analyze_activity", fake_analyze)
    first = sync.reanalyze("token", restart=True)
    assert first == {"queued": 3, "analyzed": 1, "remaining": 2, "rate_limited": True}

    budget["left"] = 10
    second = sync.reanalyze("token", restart=False)
    # Only the two left over are worked on; the one already redone is not queued again.
    assert second == {"queued": 0, "analyzed": 2, "remaining": 0, "rate_limited": False}


def test_skipped_and_error_outcomes_leave_the_queue(tmp_db, sample_activity, monkeypatch):
    _activity(sample_activity, 1, "pending")
    _activity(sample_activity, 2, "pending")
    outcomes = {1: "skipped", 2: "error"}

    def fake_analyze(act, token, max_hr, renormalize):
        db.save_analysis(act["id"], {"analysis_status": outcomes[act["id"]]})
        return outcomes[act["id"]]

    monkeypatch.setattr(sync, "analyze_activity", fake_analyze)
    assert sync.analyze_pending("token", 190, limit=None) == (0, False)
    assert [_status(1), _status(2)] == ["skipped", "error"]


def test_failed_fetch_marks_error_and_keeps_the_summary(tmp_db, sample_activity, monkeypatch):
    """A Strava 5xx or network failure must not relabel a real activity as a manual entry."""
    from strides_ai import analysis

    _activity(sample_activity, 1, "pending")
    db.save_analysis(1, {"analysis_summary": "Steady aerobic run."})

    def failing_fetch(activity_id, token):
        raise analysis.StreamFetchError("HTTP 502")

    monkeypatch.setattr(analysis, "fetch_activity_streams", failing_fetch)
    assert sync.analyze_pending("token", 190, limit=None) == (0, False)
    row = db.get_activity(1)
    assert row["analysis_status"] == "error"
    assert row["analysis_summary"] == "Steady aerobic run."


def test_auth_failure_stops_the_run_and_endpoint_returns_503(tmp_db, sample_activity, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from strides_ai import analysis
    from strides_ai.api.routers import sync as sync_router
    from strides_ai.sources import strava_source

    for i in (1, 2):
        _activity(sample_activity, i, "done")
    calls = []

    def refused(activity_id, token):
        calls.append(activity_id)
        raise analysis.StravaAuthError("Strava refused the token (HTTP 401)")

    monkeypatch.setattr(analysis, "fetch_activity_streams", refused)
    monkeypatch.setattr(strava_source, "is_configured", lambda: True)
    monkeypatch.setattr("strides_ai.sources.strava.get_settings", lambda: _Creds())
    monkeypatch.setattr("strides_ai.sources.strava.get_access_token", lambda *a: "token")

    app = FastAPI()
    app.include_router(sync_router.router, prefix="/api")
    response = TestClient(app).post("/api/strava/reanalyze?restart=true")

    assert response.status_code == 503
    assert "HTTP 401" in response.json()["detail"]
    assert len(calls) == 1  # stopped at the first refusal instead of failing every activity
    assert db.count_pending_analysis() == 2  # still queued for "Continue"


class _Creds:
    strava_client_id = "id"
    strava_client_secret = "secret"
