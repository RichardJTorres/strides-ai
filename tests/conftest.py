"""Shared fixtures for strides-ai tests."""

import sqlite3
from pathlib import Path

import pytest

from strides_ai import db


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    """Redirect DB_PATH to a temp file and initialise the schema."""
    db_file = tmp_path / "test.db"
    monkeypatch.setattr(db, "DB_PATH", db_file)
    db.init_db()
    return db_file


@pytest.fixture
def sample_activity():
    """A minimal Strava-shaped activity dict suitable for db.upsert_activity."""
    return {
        "id": 1001,
        "name": "Morning Run",
        "start_date_local": "2025-06-15T07:00:00Z",
        "distance": 10_000.0,       # metres
        "moving_time": 3_600,       # seconds (6:00/km pace)
        "elapsed_time": 3_700,
        "total_elevation_gain": 50.0,
        "average_heartrate": 145.0,
        "max_heartrate": 165,
        "average_cadence": 87.0,    # half-cadence (will be doubled → 174)
        "suffer_score": 42,
        "perceived_exertion": 5.0,
        "sport_type": "Run",
    }


@pytest.fixture
def activity_row():
    """A sqlite3.Row-compatible dict for coach/chart tests.

    Uses a real in-memory connection so the value behaves exactly like a Row.
    """
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """CREATE TABLE a (
            id INTEGER, date TEXT, name TEXT,
            distance_m REAL, moving_time_s INTEGER,
            avg_pace_s_per_km REAL, avg_hr REAL, max_hr INTEGER,
            avg_cadence REAL, elevation_gain_m REAL,
            suffer_score INTEGER, perceived_exertion REAL
        )"""
    )
    conn.execute(
        "INSERT INTO a VALUES (1,'2025-06-15','Morning Run',10000,3600,360,145,165,174,50,42,5)"
    )
    row = conn.execute("SELECT * FROM a").fetchone()
    yield row
    conn.close()
