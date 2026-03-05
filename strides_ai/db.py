"""SQLite persistence for Strava activities, conversation history, memories, and profile."""

import json
import sqlite3
from pathlib import Path
from typing import Any

DB_PATH = Path.home() / ".strides_ai" / "activities.db"

# Activity type sets — imported by sync.py to avoid duplication
RUN_TYPES = {"Run", "TrailRun", "VirtualRun"}
CYCLE_TYPES = {"Ride", "VirtualRide", "GravelRide"}

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
    avg_cadence       REAL,          -- steps/min for running, rpm for cycling
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
    mode       TEXT NOT NULL DEFAULT 'running',
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

CREATE_SETTINGS = """
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
)
"""

CREATE_PROFILES = """
CREATE TABLE IF NOT EXISTS profiles (
    mode        TEXT PRIMARY KEY,
    fields_json TEXT NOT NULL,
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
)
"""

CREATE_CALENDAR_PREFS = """
CREATE TABLE IF NOT EXISTS calendar_prefs (
    id            INTEGER PRIMARY KEY CHECK (id = 1),
    rest_days     TEXT NOT NULL DEFAULT '[]',
    long_run_days TEXT NOT NULL DEFAULT '[]',
    frequency     INTEGER NOT NULL DEFAULT 4,
    blocked_days  TEXT NOT NULL DEFAULT '[]',
    races         TEXT NOT NULL DEFAULT '[]'
)
"""

CREATE_TRAINING_PLAN = """
CREATE TABLE IF NOT EXISTS training_plan (
    date         TEXT PRIMARY KEY,
    workout_type TEXT,
    description  TEXT,
    distance_km  REAL,
    duration_min INTEGER,
    intensity    TEXT,
    generated_at TEXT NOT NULL DEFAULT (datetime('now'))
)
"""
def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _migrate_conversations(conn: sqlite3.Connection) -> None:
    """Add mode column to conversations table if it does not exist yet."""
    try:
        conn.execute("ALTER TABLE conversations ADD COLUMN mode TEXT NOT NULL DEFAULT 'running'")
    except sqlite3.OperationalError:
        pass  # column already exists


def init_db() -> None:
    with _connect() as conn:
        conn.execute(CREATE_TABLE)
        conn.execute(CREATE_CONVERSATIONS)
        conn.execute(CREATE_MEMORIES)
        conn.execute(CREATE_SETTINGS)
        conn.execute(CREATE_PROFILES)
        conn.execute(CREATE_CALENDAR_PREFS)
        conn.execute(CREATE_TRAINING_PLAN)
        _migrate_conversations(conn)


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

    # Pace in seconds per km (works for both running and cycling)
    if distance_m > 0 and moving_time_s > 0:
        avg_pace_s_per_km = moving_time_s / (distance_m / 1000)
    else:
        avg_pace_s_per_km = None

    # Strava returns running cadence as average steps per minute for one foot;
    # multiply by 2 for total (running cadence convention).
    # Cycling cadence is already full RPM — do not double.
    sport = activity.get("sport_type", activity.get("type", ""))
    raw_cadence = activity.get("average_cadence")
    if raw_cadence is not None:
        avg_cadence = raw_cadence * 2 if sport in RUN_TYPES else raw_cadence
    else:
        avg_cadence = None

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
                "sport_type": sport,
                "raw_json": json.dumps(activity),
            },
        )


def get_all_activities() -> list[sqlite3.Row]:
    """Return all activities ordered newest-first."""
    with _connect() as conn:
        return conn.execute(
            "SELECT * FROM activities ORDER BY date DESC"
        ).fetchall()


def get_activities_for_mode(mode: str) -> list[sqlite3.Row]:
    """Return activities filtered to the active mode, newest-first."""
    with _connect() as conn:
        if mode == "running":
            placeholders = ",".join("?" * len(RUN_TYPES))
            return conn.execute(
                f"SELECT * FROM activities WHERE sport_type IN ({placeholders}) ORDER BY date DESC",
                tuple(RUN_TYPES),
            ).fetchall()
        elif mode == "cycling":
            placeholders = ",".join("?" * len(CYCLE_TYPES))
            return conn.execute(
                f"SELECT * FROM activities WHERE sport_type IN ({placeholders}) ORDER BY date DESC",
                tuple(CYCLE_TYPES),
            ).fetchall()
        else:  # hybrid
            return conn.execute(
                "SELECT * FROM activities ORDER BY date DESC"
            ).fetchall()


# ── Profiles ─────────────────────────────────────────────────────────────────

def get_profile_fields(mode: str) -> dict | None:
    """Return the profile fields dict for the given mode, or None if not saved."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT fields_json FROM profiles WHERE mode = ?", (mode,)
        ).fetchone()
    return json.loads(row["fields_json"]) if row else None


def save_profile_fields(mode: str, fields: dict) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO profiles (mode, fields_json, updated_at) VALUES (?, ?, datetime('now'))",
            (mode, json.dumps(fields)),
        )


# ── Settings ─────────────────────────────────────────────────────────────────

def get_setting(key: str, default: str | None = None) -> str | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
    return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (key, value),
        )


# ── Conversation history ────────────────────────────────────────────────────

def save_message(role: str, content: str, mode: str = "running") -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO conversations (role, content, mode) VALUES (?, ?, ?)",
            (role, content, mode),
        )


def get_recent_messages(n: int = 40, mode: str | None = None) -> list[dict]:
    """Return the last *n* messages in chronological order, optionally filtered by mode."""
    with _connect() as conn:
        if mode:
            rows = conn.execute(
                "SELECT id, role, content, created_at FROM conversations WHERE mode = ? ORDER BY id DESC LIMIT ?",
                (mode, n),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, role, content, created_at FROM conversations ORDER BY id DESC LIMIT ?",
                (n,),
            ).fetchall()
    return [dict(r) for r in reversed(rows)]


def get_messages_before(before_id: int, limit: int = 40, mode: str | None = None) -> list[dict]:
    """Return up to *limit* messages with id < before_id, in chronological order."""
    with _connect() as conn:
        if mode:
            rows = conn.execute(
                "SELECT id, role, content, created_at FROM conversations WHERE id < ? AND mode = ? ORDER BY id DESC LIMIT ?",
                (before_id, mode, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, role, content, created_at FROM conversations WHERE id < ? ORDER BY id DESC LIMIT ?",
                (before_id, limit),
            ).fetchall()
    return [dict(r) for r in reversed(rows)]


def get_message_count(mode: str | None = None) -> int:
    """Return the total number of stored messages, optionally filtered by mode."""
    with _connect() as conn:
        if mode:
            return conn.execute(
                "SELECT COUNT(*) FROM conversations WHERE mode = ?", (mode,)
            ).fetchone()[0]
        return conn.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]


def search_messages(query: str, limit: int = 20, mode: str | None = None) -> list[dict]:
    """Case-insensitive substring search. Returns newest-first."""
    with _connect() as conn:
        if mode:
            rows = conn.execute(
                "SELECT id, role, content, created_at FROM conversations WHERE content LIKE ? AND mode = ? ORDER BY id DESC LIMIT ?",
                (f"%{query}%", mode, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, role, content, created_at FROM conversations WHERE content LIKE ? ORDER BY id DESC LIMIT ?",
                (f"%{query}%", limit),
            ).fetchall()
    return [dict(r) for r in rows]


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


# ── Calendar ─────────────────────────────────────────────────────────────────

def get_calendar_prefs() -> dict:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM calendar_prefs WHERE id = 1").fetchone()
    if row is None:
        return {"rest_days": [], "long_run_days": [], "frequency": 4, "blocked_days": [], "races": []}
    return {
        "rest_days": json.loads(row["rest_days"]),
        "long_run_days": json.loads(row["long_run_days"]),
        "frequency": row["frequency"],
        "blocked_days": json.loads(row["blocked_days"]),
        "races": json.loads(row["races"]),
    }


def save_calendar_prefs(rest_days: list, long_run_days: list, frequency: int, blocked_days: list, races: list) -> None:
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO calendar_prefs (id, rest_days, long_run_days, frequency, blocked_days, races)
            VALUES (1, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                rest_days = excluded.rest_days,
                long_run_days = excluded.long_run_days,
                frequency = excluded.frequency,
                blocked_days = excluded.blocked_days,
                races = excluded.races
            """,
            (json.dumps(rest_days), json.dumps(long_run_days), frequency, json.dumps(blocked_days), json.dumps(races)),
        )


def get_training_plan(start_date: str | None = None, end_date: str | None = None) -> list[dict]:
    with _connect() as conn:
        if start_date and end_date:
            rows = conn.execute(
                "SELECT * FROM training_plan WHERE date BETWEEN ? AND ? ORDER BY date",
                (start_date, end_date),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM training_plan ORDER BY date").fetchall()
    return [dict(r) for r in rows]


def save_training_plan(workouts: list[dict]) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM training_plan")
        conn.executemany(
            """
            INSERT INTO training_plan (date, workout_type, description, distance_km, duration_min, intensity)
            VALUES (:date, :workout_type, :description, :distance_km, :duration_min, :intensity)
            """,
            workouts,
        )
