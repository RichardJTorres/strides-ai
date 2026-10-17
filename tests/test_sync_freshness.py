"""last_sync_at is recorded on every completed sync and surfaced via /status."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from strides_ai import db
from strides_ai.api.routers import status, sync


class _FakeBackend:
    label = "fake"
    supports_attachments = False


def _app():
    app = FastAPI()
    app.state.mode = "running"
    app.state.backend = _FakeBackend()
    app.include_router(sync.router)
    app.include_router(status.router)
    return app


def test_status_reports_no_sync_before_any_sync_runs(tmp_db):
    client = TestClient(_app())
    assert client.get("/status").json()["last_sync_at"] is None


def test_sync_all_records_timestamp_even_with_zero_new_items(tmp_db, monkeypatch):
    monkeypatch.setattr(sync, "configured_sources", lambda: [])
    client = TestClient(_app())

    response = client.post("/sync")
    assert response.json() == {"total": 0, "sources": {}}

    last_sync_at = client.get("/status").json()["last_sync_at"]
    assert last_sync_at is not None


def test_sync_all_updates_timestamp_on_each_call(tmp_db, monkeypatch):
    monkeypatch.setattr(sync, "configured_sources", lambda: [])
    client = TestClient(_app())

    client.post("/sync")
    first = db.get_setting("last_sync_at")
    client.post("/sync")
    second = db.get_setting("last_sync_at")

    assert first is not None and second is not None
    assert second >= first
