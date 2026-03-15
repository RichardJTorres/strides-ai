"""
Database package.

Re-exports all public symbols so existing callers (CLI, coach, sync, analysis)
continue to work with `from strides_ai import db; db.get_activity(id)`.

FastAPI routes should prefer injecting a Session via `Depends(get_session)` and
calling the domain modules directly (e.g. `from strides_ai.db import activities`).
"""

from .engine import DB_PATH, get_engine, get_session, init_db, reset_engine
from .models import (
    Activity,
    CalendarPref,
    Conversation,
    Memory,
    Profile,
    Setting,
    TrainingPlan,
    CYCLE_TYPES,
    RUN_TYPES,
)
from . import activities as _act
from . import calendar as _cal
from . import conversations as _conv
from . import memories as _mem
from . import profiles as _prof
from . import settings as _sett

# Keep _get_engine / _reset_engine aliases so any internal code that used the
# private names doesn't break.
_get_engine = get_engine
_reset_engine = reset_engine

__all__ = [
    # engine
    "DB_PATH",
    "get_engine",
    "get_session",
    "init_db",
    "reset_engine",
    # models
    "Activity",
    "CalendarPref",
    "Conversation",
    "Memory",
    "Profile",
    "Setting",
    "TrainingPlan",
    "CYCLE_TYPES",
    "RUN_TYPES",
    # convenience wrappers (see below)
    "get_latest_activity_date",
    "get_stored_ids",
    "upsert_activity",
    "get_all_activities",
    "get_activities_for_mode",
    "get_activity",
    "save_analysis",
    "get_activities_pending_analysis",
    "renormalize_effort_efficiency",
    "get_profile_fields",
    "save_profile_fields",
    "get_setting",
    "set_setting",
    "save_message",
    "get_recent_messages",
    "get_messages_before",
    "get_message_count",
    "search_messages",
    "save_memory",
    "get_all_memories",
    "get_calendar_prefs",
    "save_calendar_prefs",
    "get_training_plan",
    "save_planned_workout",
    "delete_planned_workout",
    "save_workout_nutrition",
    "get_upcoming_planned_workouts",
]

# ── Helpers ───────────────────────────────────────────────────────────────────

from contextlib import contextmanager
from sqlmodel import Session


@contextmanager
def _session():
    with Session(get_engine()) as s:
        yield s


# ── Activities ────────────────────────────────────────────────────────────────


def get_latest_activity_date() -> str | None:
    with _session() as s:
        return _act.get_latest_activity_date(s)


def get_stored_ids() -> set[int]:
    with _session() as s:
        return _act.get_stored_ids(s)


def upsert_activity(activity: dict) -> None:
    with _session() as s:
        _act.upsert(s, activity)


def get_all_activities() -> list[dict]:
    with _session() as s:
        return [r.model_dump() for r in _act.get_all(s)]


def get_activities_for_mode(mode: str) -> list[dict]:
    with _session() as s:
        return [r.model_dump() for r in _act.get_for_mode(s, mode)]


def get_activity(activity_id: int) -> dict | None:
    with _session() as s:
        row = _act.get(s, activity_id)
        return row.model_dump() if row else None


def save_analysis(activity_id: int, metrics: dict) -> None:
    with _session() as s:
        _act.update_analysis(s, activity_id, metrics)


def get_activities_pending_analysis(limit: int = 10) -> list[dict]:
    with _session() as s:
        return [r.model_dump() for r in _act.get_pending_analysis(s, limit)]


def renormalize_effort_efficiency() -> None:
    with _session() as s:
        _act.renormalize_effort_efficiency(s)


# ── Profiles ──────────────────────────────────────────────────────────────────


def get_profile_fields(mode: str) -> dict | None:
    with _session() as s:
        return _prof.get_fields(s, mode)


def save_profile_fields(mode: str, fields: dict) -> None:
    with _session() as s:
        _prof.save_fields(s, mode, fields)


# ── Settings ──────────────────────────────────────────────────────────────────


def get_setting(key: str, default: str | None = None) -> str | None:
    with _session() as s:
        return _sett.get(s, key, default)


def set_setting(key: str, value: str) -> None:
    with _session() as s:
        _sett.set(s, key, value)


# ── Conversations ─────────────────────────────────────────────────────────────


def save_message(role: str, content: str, mode: str = "running", model: str | None = None) -> None:
    with _session() as s:
        _conv.save(s, role, content, mode, model)


def get_recent_messages(n: int = 40, mode: str | None = None) -> list[dict]:
    with _session() as s:
        return [r.model_dump() for r in _conv.get_recent(s, n, mode)]


def get_messages_before(before_id: int, limit: int = 40, mode: str | None = None) -> list[dict]:
    with _session() as s:
        return [r.model_dump() for r in _conv.get_before(s, before_id, limit, mode)]


def get_message_count(mode: str | None = None) -> int:
    with _session() as s:
        return _conv.count(s, mode)


def search_messages(query: str, limit: int = 20, mode: str | None = None) -> list[dict]:
    with _session() as s:
        return [r.model_dump() for r in _conv.search(s, query, limit, mode)]


# ── Memories ──────────────────────────────────────────────────────────────────


def save_memory(category: str, content: str) -> str:
    with _session() as s:
        return _mem.save(s, category, content)


def get_all_memories() -> list[dict]:
    with _session() as s:
        return [r.model_dump() for r in _mem.get_all(s)]


# ── Calendar ──────────────────────────────────────────────────────────────────


def get_calendar_prefs() -> dict:
    with _session() as s:
        return _cal.get_prefs(s)


def save_calendar_prefs(blocked_days: list, races: list) -> None:
    with _session() as s:
        _cal.save_prefs(s, blocked_days, races)


def get_training_plan(start_date: str | None = None, end_date: str | None = None) -> list[dict]:
    with _session() as s:
        return [r.model_dump() for r in _cal.get_plan(s, start_date, end_date)]


def save_planned_workout(
    date: str,
    workout_type: str,
    description: str | None,
    distance_km: float | None,
    elevation_m: float | None,
    duration_min: int | None,
    intensity: str | None,
) -> None:
    with _session() as s:
        _cal.save_planned_workout(
            s, date, workout_type, description, distance_km, elevation_m, duration_min, intensity
        )


def delete_planned_workout(date: str) -> None:
    with _session() as s:
        _cal.delete_planned_workout(s, date)


def save_workout_nutrition(date: str, nutrition: dict) -> None:
    with _session() as s:
        _cal.save_workout_nutrition(s, date, nutrition)


def get_upcoming_planned_workouts(days: int = 14) -> list[dict]:
    with _session() as s:
        return [r.model_dump() for r in _cal.get_upcoming_workouts(s, days)]
