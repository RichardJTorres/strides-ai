"""SQLite persistence for Strava activities, conversation history, memories, and profile."""

import json
import sqlite3
from pathlib import Path
from typing import Any

DB_PATH = Path.home() / ".strides_ai" / "activities.db"

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS activities (
    id                INTEGER PRIMARY KEY,
    name              TEXT,
    date              TEXT,          -- ISO-8601 local date
    distance_m        REAL,          -- metres
    moving_time_s     INTEGER,       -- seconds
    elapsed_time_s    INTEGER,       -- seconds
    elevation_gain_m  REAL,          -- metres
    avg_pace_s_per_km REAL,          -- seconds per km (derived)
    avg_hr            REAL,
    max_hr            INTEGER,
    avg_cadence       REAL,          -- steps per minute (strava stores half-cadence)
    suffer_score      INTEGER,
    perceived_exertion REAL,
    sport_type        TEXT,
    raw_json          TEXT           -- full Strava payload for future use
)
"""

CREATE_CONVERSATIONS = """
CREATE TABLE IF NOT EXISTS conversations (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    role       TEXT NOT NULL,   -- 'user' or 'assistant'
    content    TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
)
"""

CREATE_MEMORIES = """
CREATE TABLE IF NOT EXISTS memories (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    category   TEXT NOT NULL,
    content    TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
)
"""

def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.execute(CREATE_TABLE)
        conn.execute(CREATE_CONVERSATIONS)
        conn.execute(CREATE_MEMORIES)


def get_latest_activity_date() -> str | None:
    """Return the ISO date of the most recent stored activity, or None."""
    with _connect() as conn:
        row = conn.execute("SELECT MAX(date) FROM activities").fetchone()
        return row[0] if row else None


def get_stored_ids() -> set[int]:
    with _connect() as conn:
        rows = conn.execute("SELECT id FROM activities").fetchall()
        return {r["id"] for r in rows}


def upsert_activity(activity: dict[str, Any]) -> None:
    """Insert or replace an activity row derived from a Strava API response."""
    distance_m: float = activity.get("distance", 0)
    moving_time_s: int = activity.get("moving_time", 0)

    # Pace in seconds per km
    if distance_m > 0 and moving_time_s > 0:
        avg_pace_s_per_km = moving_time_s / (distance_m / 1000)
    else:
        avg_pace_s_per_km = None

    # Strava returns cadence as average steps per minute for one foot;
    # multiply by 2 for total (running cadence convention).
    raw_cadence = activity.get("average_cadence")
    avg_cadence = raw_cadence * 2 if raw_cadence is not None else None

    with _connect() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO activities (
                id, name, date, distance_m, moving_time_s, elapsed_time_s,
                elevation_gain_m, avg_pace_s_per_km, avg_hr, max_hr,
                avg_cadence, suffer_score, perceived_exertion, sport_type, raw_json
            ) VALUES (
                :id, :name, :date, :distance_m, :moving_time_s, :elapsed_time_s,
                :elevation_gain_m, :avg_pace_s_per_km, :avg_hr, :max_hr,
                :avg_cadence, :suffer_score, :perceived_exertion, :sport_type, :raw_json
            )
            """,
            {
                "id": activity["id"],
                "name": activity.get("name"),
                "date": activity.get("start_date_local", "")[:10],
                "distance_m": distance_m,
                "moving_time_s": moving_time_s,
                "elapsed_time_s": activity.get("elapsed_time"),
                "elevation_gain_m": activity.get("total_elevation_gain"),
                "avg_pace_s_per_km": avg_pace_s_per_km,
                "avg_hr": activity.get("average_heartrate"),
                "max_hr": activity.get("max_heartrate"),
                "avg_cadence": avg_cadence,
                "suffer_score": activity.get("suffer_score"),
                "perceived_exertion": activity.get("perceived_exertion"),
                "sport_type": activity.get("sport_type", activity.get("type")),
                "raw_json": json.dumps(activity),
            },
        )


def get_all_activities() -> list[sqlite3.Row]:
    """Return all activities ordered newest-first."""
    with _connect() as conn:
        return conn.execute(
            "SELECT * FROM activities ORDER BY date DESC"
        ).fetchall()


# ── Conversation history ────────────────────────────────────────────────────

def save_message(role: str, content: str) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO conversations (role, content) VALUES (?, ?)",
            (role, content),
        )


def get_recent_messages(n: int = 40) -> list[dict]:
    """Return the last *n* messages in chronological order."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT role, content FROM conversations ORDER BY id DESC LIMIT ?",
            (n,),
        ).fetchall()
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]


# ── Memories ────────────────────────────────────────────────────────────────

def save_memory(category: str, content: str) -> str:
    """Persist a memory. Returns a status string for the tool result."""
    try:
        with _connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO memories (category, content) VALUES (?, ?)",
                (category, content),
            )
        return "Memory saved."
    except Exception as exc:
        return f"Error: {exc}"


def get_all_memories() -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, category, content, created_at FROM memories ORDER BY created_at"
        ).fetchall()
    return [dict(r) for r in rows]
