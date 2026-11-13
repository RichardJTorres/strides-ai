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
    ChatTurn,
    Conversation,
    ExerciseTemplate,
    Memory,
    Profile,
    Setting,
    CalendarEntry,
    PlanRow,
    RaceDetail,
    WorkoutDetail,
    CYCLE_TYPES,
    LIFT_TYPES,
    RUN_TYPES,
)
from . import activities as _act
from . import calendar as _cal
from . import conversations as _conv
from . import exercise_templates as _tmpl
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
    "ChatTurn",
    "Conversation",
    "ExerciseTemplate",
    "Memory",
    "Profile",
    "Setting",
    "CalendarEntry",
    "PlanRow",
    "RaceDetail",
    "WorkoutDetail",
    "CYCLE_TYPES",
    "LIFT_TYPES",
    "RUN_TYPES",
    # convenience wrappers (see below)
    "get_latest_activity_date",
    "get_latest_hevy_date",
    "get_stored_ids",
    "upsert_activity",
    "upsert_hevy_workout",
    "upsert_canonical_activity",
    "get_all_activities",
    "get_activities_for_mode",
    "get_activity",
    "save_analysis",
    "get_activities_pending_analysis",
    "renormalize_effort_efficiency",
    "get_profile_fields",
    "get_max_hr",
    "get_setting",
    "set_setting",
    "save_message",
    "get_recent_messages",
    "log_mutation",
    "get_messages_before",
    "get_message_count",
    "search_messages",
    "save_memory",
    "get_all_memories",
    "get_calendar_prefs",
    "save_calendar_prefs",
    "get_training_plan",
    "apply_calendar_changes",
    "get_upcoming_planned_workouts",
    "upsert_exercise_template",
    "get_exercise_template_muscle_map",
    "get_exercise_template_count",
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


def get_latest_hevy_date() -> str | None:
    """Return the date of the most recent HEVY workout in the DB, or None."""
    with _session() as s:
        from .models import Activity
        import sqlalchemy as sa
        from sqlmodel import select

        result = s.execute(
            select(sa.func.max(Activity.date)).where(
                sa.or_(
                    Activity.source == "hevy",
                    sa.and_(
                        Activity.source.is_(None),
                        Activity.external_id.is_not(None),
                    ),
                )
            )
        ).scalar()
        return result


def get_stored_ids() -> set[int]:
    with _session() as s:
        return _act.get_stored_ids(s)


def upsert_activity(activity: dict) -> None:
    with _session() as s:
        _act.upsert(s, activity)


def upsert_hevy_workout(activity: dict) -> None:
    with _session() as s:
        _act.upsert_hevy(s, activity)


def upsert_canonical_activity(activity) -> None:
    with _session() as s:
        _act.upsert_canonical(s, activity)


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


def get_profile_fields(mode: str | None = None) -> dict | None:
    with _session() as s:
        return _prof.get_fields(s, mode)


def get_max_hr(default: int = 190) -> int:
    with _session() as s:
        return _prof.get_max_hr(s, default)


# ── Settings ──────────────────────────────────────────────────────────────────


def get_setting(key: str, default: str | None = None) -> str | None:
    with _session() as s:
        return _sett.get(s, key, default)


def set_setting(key: str, value: str) -> None:
    with _session() as s:
        _sett.set(s, key, value)


def get_unit_system():
    with _session() as s:
        return _sett.get_unit_system(s)


# ── Conversations ─────────────────────────────────────────────────────────────


def save_message(role: str, content: str, mode: str = "running", model: str | None = None) -> None:
    with _session() as s:
        _conv.save(s, role, content, mode, model)


def log_mutation(turn_id: int | None, kind: str, state: str, payload: dict) -> None:
    from . import mutations

    with _session() as s:
        mutations.log_now(s, turn_id, kind, state, payload)


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


def save_memory(category: str, content: str, **metadata) -> str:
    with _session() as s:
        return _mem.save(s, category, content, **metadata)


def get_all_memories() -> list[dict]:
    with _session() as s:
        return [r.model_dump() for r in _mem.get_all(s)]


# ── Calendar ──────────────────────────────────────────────────────────────────


def get_calendar_prefs() -> dict:
    with _session() as s:
        return _cal.get_prefs(s)


def save_calendar_prefs(blocked_days: list) -> None:
    with _session() as s:
        _cal.save_prefs(s, blocked_days)


def get_training_plan(start_date: str | None = None, end_date: str | None = None) -> list[dict]:
    """Calendar entries (flattened with their detail), oldest first."""
    with _session() as s:
        return _cal.get_plan_rows(s, start_date, end_date)


def apply_calendar_changes(
    ops: list[dict], request_id: str | None = None, turn_id: int | None = None
) -> dict:
    with _session() as s:
        return _cal.apply_changes(s, ops, request_id, turn_id)


def get_upcoming_planned_workouts(days: int = 14) -> list[dict]:
    with _session() as s:
        return _cal.get_upcoming_workouts(s, days)


# ── Exercise templates ────────────────────────────────────────────────────────


def upsert_exercise_template(template: dict) -> None:
    with _session() as s:
        _tmpl.upsert(s, template)
        s.commit()


def get_exercise_template_muscle_map() -> dict[str, str]:
    with _session() as s:
        return _tmpl.get_muscle_map(s)


def get_exercise_template_count() -> int:
    with _session() as s:
        return _tmpl.count(s)
