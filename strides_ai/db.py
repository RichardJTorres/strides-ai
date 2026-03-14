"""SQLite persistence using SQLModel + Alembic."""

import json
from datetime import date as date_cls, timedelta
from pathlib import Path
from typing import Any, Optional

import sqlalchemy as sa
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlmodel import Column, Field, Session, SQLModel, create_engine, select

DB_PATH = Path.home() / ".strides_ai" / "activities.db"

# Activity type sets — imported by sync.py to avoid duplication
RUN_TYPES = {"Run", "TrailRun", "VirtualRun"}
CYCLE_TYPES = {"Ride", "VirtualRide", "GravelRide"}


# ── Models ────────────────────────────────────────────────────────────────────


class Activity(SQLModel, table=True):
    __tablename__ = "activities"

    id: int = Field(primary_key=True)
    name: Optional[str] = None
    date: Optional[str] = None
    distance_m: Optional[float] = None
    moving_time_s: Optional[int] = None
    elapsed_time_s: Optional[int] = None
    elevation_gain_m: Optional[float] = None
    avg_pace_s_per_km: Optional[float] = None
    avg_hr: Optional[float] = None
    max_hr: Optional[int] = None
    avg_cadence: Optional[float] = None
    suffer_score: Optional[int] = None
    perceived_exertion: Optional[float] = None
    sport_type: Optional[str] = None
    raw_json: Optional[str] = None

    # Analysis columns (populated by analysis pipeline)
    cardiac_decoupling_pct: Optional[float] = None
    hr_zone_1_pct: Optional[float] = None
    hr_zone_2_pct: Optional[float] = None
    hr_zone_3_pct: Optional[float] = None
    hr_zone_4_pct: Optional[float] = None
    hr_zone_5_pct: Optional[float] = None
    pace_fade_seconds: Optional[float] = None
    cadence_std_dev: Optional[float] = None
    effort_efficiency_raw: Optional[float] = None
    effort_efficiency_score: Optional[float] = None
    elevation_per_mile: Optional[float] = None
    high_elevation_flag: Optional[int] = None
    suffer_score_mismatch_flag: Optional[int] = None
    analysis_summary: Optional[str] = None
    deep_dive_report: Optional[str] = None
    deep_dive_completed_at: Optional[str] = None
    analysis_status: Optional[str] = None


class Conversation(SQLModel, table=True):
    __tablename__ = "conversations"

    id: Optional[int] = Field(default=None, primary_key=True)
    role: str
    content: str
    mode: str = Field(default="running")
    model: Optional[str] = None
    created_at: Optional[str] = Field(
        default=None,
        sa_column=Column(sa.Text, server_default=sa.text("datetime('now')")),
    )


class Memory(SQLModel, table=True):
    __tablename__ = "memories"

    id: Optional[int] = Field(default=None, primary_key=True)
    category: str
    content: str = Field(sa_column=Column(sa.Text, unique=True, nullable=False))
    created_at: Optional[str] = Field(
        default=None,
        sa_column=Column(sa.Text, server_default=sa.text("datetime('now')")),
    )


class Setting(SQLModel, table=True):
    __tablename__ = "settings"

    key: str = Field(primary_key=True)
    value: str


class Profile(SQLModel, table=True):
    __tablename__ = "profiles"

    mode: str = Field(primary_key=True)
    fields_json: str
    updated_at: Optional[str] = Field(
        default=None,
        sa_column=Column(sa.Text, server_default=sa.text("datetime('now')")),
    )


class CalendarPref(SQLModel, table=True):
    __tablename__ = "calendar_prefs"

    id: int = Field(
        default=1,
        sa_column=Column(sa.Integer, sa.CheckConstraint("id = 1"), primary_key=True),
    )
    rest_days: str = Field(
        default="[]",
        sa_column=Column(sa.Text, nullable=False, server_default="'[]'"),
    )
    long_run_days: str = Field(
        default="[]",
        sa_column=Column(sa.Text, nullable=False, server_default="'[]'"),
    )
    frequency: int = Field(
        default=4,
        sa_column=Column(sa.Integer, nullable=False, server_default="4"),
    )
    blocked_days: str = Field(
        default="[]",
        sa_column=Column(sa.Text, nullable=False, server_default="'[]'"),
    )
    races: str = Field(
        default="[]",
        sa_column=Column(sa.Text, nullable=False, server_default="'[]'"),
    )


class TrainingPlan(SQLModel, table=True):
    __tablename__ = "training_plan"

    date: str = Field(primary_key=True)
    workout_type: Optional[str] = None
    description: Optional[str] = None
    distance_km: Optional[float] = None
    elevation_m: Optional[float] = None
    duration_min: Optional[int] = None
    intensity: Optional[str] = None
    nutrition_json: Optional[str] = None
    created_at: Optional[str] = Field(
        default=None,
        sa_column=Column(sa.Text, server_default=sa.text("datetime('now')")),
    )


# ── Engine ────────────────────────────────────────────────────────────────────

_engine: sa.engine.Engine | None = None


def _get_engine() -> sa.engine.Engine:
    global _engine
    if _engine is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _engine = create_engine(
            f"sqlite:///{DB_PATH}",
            connect_args={"check_same_thread": False},
        )
    return _engine


def _reset_engine() -> None:
    global _engine
    if _engine is not None:
        _engine.dispose()
        _engine = None


def _make_alembic_config():
    from alembic.config import Config

    alembic_dir = Path(__file__).parent.parent / "alembic"
    cfg = Config()
    cfg.set_main_option("script_location", str(alembic_dir))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{DB_PATH}")
    return cfg


def init_db() -> None:
    _reset_engine()
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    from alembic import command as alembic_command

    cfg = _make_alembic_config()

    with _get_engine().connect() as conn:
        tables = (
            conn.execute(sa.text("SELECT name FROM sqlite_master WHERE type='table'"))
            .scalars()
            .all()
        )

    if "activities" in tables and "alembic_version" not in tables:
        # Existing database — stamp without running DDL
        alembic_command.stamp(cfg, "head")
    else:
        # Fresh database or already stamped — run migrations
        alembic_command.upgrade(cfg, "head")


# ── Activities ────────────────────────────────────────────────────────────────


def get_latest_activity_date() -> str | None:
    """Return the ISO date of the most recent stored activity, or None."""
    with Session(_get_engine()) as session:
        return session.execute(select(sa.func.max(Activity.date))).scalar()


def get_stored_ids() -> set[int]:
    with Session(_get_engine()) as session:
        return set(session.execute(select(Activity.id)).scalars().all())


def upsert_activity(activity: dict[str, Any]) -> None:
    """Insert or replace an activity row derived from a Strava API response."""
    distance_m: float = activity.get("distance", 0)
    moving_time_s: int = activity.get("moving_time", 0)

    if distance_m > 0 and moving_time_s > 0:
        avg_pace_s_per_km = moving_time_s / (distance_m / 1000)
    else:
        avg_pace_s_per_km = None

    sport = activity.get("sport_type", activity.get("type", ""))
    raw_cadence = activity.get("average_cadence")
    if raw_cadence is not None:
        avg_cadence = raw_cadence * 2 if sport in RUN_TYPES else raw_cadence
    else:
        avg_cadence = None

    values = {
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
    }

    with Session(_get_engine()) as session:
        stmt = sqlite_insert(Activity).values(**values)
        stmt = stmt.on_conflict_do_update(
            index_elements=["id"],
            set_={k: v for k, v in values.items() if k != "id"},
        )
        session.execute(stmt)
        session.commit()


def get_all_activities() -> list[dict]:
    """Return all activities ordered newest-first."""
    with Session(_get_engine()) as session:
        rows = session.exec(select(Activity).order_by(Activity.date.desc())).all()
    return [r.model_dump() for r in rows]


def get_activities_for_mode(mode: str) -> list[dict]:
    """Return activities filtered to the active mode, newest-first."""
    with Session(_get_engine()) as session:
        if mode == "running":
            stmt = (
                select(Activity)
                .where(Activity.sport_type.in_(RUN_TYPES))
                .order_by(Activity.date.desc())
            )
        elif mode == "cycling":
            stmt = (
                select(Activity)
                .where(Activity.sport_type.in_(CYCLE_TYPES))
                .order_by(Activity.date.desc())
            )
        else:  # hybrid
            stmt = select(Activity).order_by(Activity.date.desc())
        rows = session.exec(stmt).all()
    return [r.model_dump() for r in rows]


def get_activity(activity_id: int) -> dict | None:
    """Return a single activity by ID, or None if not found."""
    with Session(_get_engine()) as session:
        row = session.get(Activity, activity_id)
    return row.model_dump() if row else None


def save_analysis(activity_id: int, metrics: dict) -> None:
    """Write computed analysis columns back to a single activity row."""
    if not metrics:
        return
    with _get_engine().connect() as conn:
        cols = ", ".join(f"{k} = :{k}" for k in metrics)
        stmt = sa.text(f"UPDATE activities SET {cols} WHERE id = :_id")
        conn.execute(stmt, {**metrics, "_id": activity_id})
        conn.commit()


def get_activities_pending_analysis(limit: int = 10) -> list[dict]:
    """Return up to *limit* activities where analysis_status is 'pending' or NULL."""
    with Session(_get_engine()) as session:
        stmt = (
            select(Activity)
            .where(
                sa.or_(
                    Activity.analysis_status == "pending",
                    Activity.analysis_status.is_(None),
                )
            )
            .order_by(Activity.date.desc())
            .limit(limit)
        )
        rows = session.exec(stmt).all()
    return [r.model_dump() for r in rows]


def renormalize_effort_efficiency() -> None:
    """
    Re-score effort_efficiency_score for all rows using inverted min-max normalization.
    Lower raw ratio (faster pace / lower HR) = more efficient = higher score.
    Formula: score = 100 * (max_raw - raw) / (max_raw - min_raw)
    """
    with _get_engine().connect() as conn:
        result = conn.execute(
            sa.text(
                "SELECT MIN(effort_efficiency_raw), MAX(effort_efficiency_raw)"
                " FROM activities WHERE effort_efficiency_raw IS NOT NULL"
            )
        ).one()
        min_raw, max_raw = result

        if min_raw is None:
            return

        if min_raw == max_raw:
            conn.execute(
                sa.text(
                    "UPDATE activities SET effort_efficiency_score = 50.0"
                    " WHERE effort_efficiency_raw IS NOT NULL"
                )
            )
        else:
            conn.execute(
                sa.text(
                    "UPDATE activities"
                    " SET effort_efficiency_score = ROUND("
                    "   100.0 * (:max_raw - effort_efficiency_raw) / (:max_raw - :min_raw), 2"
                    " )"
                    " WHERE effort_efficiency_raw IS NOT NULL"
                ),
                {"min_raw": min_raw, "max_raw": max_raw},
            )
        conn.commit()


# ── Profiles ─────────────────────────────────────────────────────────────────


def get_profile_fields(mode: str) -> dict | None:
    """Return the profile fields dict for the given mode, or None if not saved."""
    with Session(_get_engine()) as session:
        row = session.get(Profile, mode)
    return json.loads(row.fields_json) if row else None


def save_profile_fields(mode: str, fields: dict) -> None:
    with Session(_get_engine()) as session:
        stmt = sqlite_insert(Profile).values(mode=mode, fields_json=json.dumps(fields))
        stmt = stmt.on_conflict_do_update(
            index_elements=["mode"],
            set_={"fields_json": json.dumps(fields), "updated_at": sa.text("datetime('now')")},
        )
        session.execute(stmt)
        session.commit()


# ── Settings ─────────────────────────────────────────────────────────────────


def get_setting(key: str, default: str | None = None) -> str | None:
    with Session(_get_engine()) as session:
        row = session.get(Setting, key)
    return row.value if row else default


def set_setting(key: str, value: str) -> None:
    with Session(_get_engine()) as session:
        stmt = sqlite_insert(Setting).values(key=key, value=value)
        stmt = stmt.on_conflict_do_update(index_elements=["key"], set_={"value": value})
        session.execute(stmt)
        session.commit()


# ── Conversation history ──────────────────────────────────────────────────────


def save_message(role: str, content: str, mode: str = "running", model: str | None = None) -> None:
    with Session(_get_engine()) as session:
        session.add(Conversation(role=role, content=content, mode=mode, model=model))
        session.commit()


def get_recent_messages(n: int = 40, mode: str | None = None) -> list[dict]:
    """Return the last *n* messages in chronological order, optionally filtered by mode."""
    with Session(_get_engine()) as session:
        stmt = select(Conversation).order_by(Conversation.id.desc()).limit(n)
        if mode:
            stmt = stmt.where(Conversation.mode == mode)
        rows = session.exec(stmt).all()
    return [r.model_dump() for r in reversed(rows)]


def get_messages_before(before_id: int, limit: int = 40, mode: str | None = None) -> list[dict]:
    """Return up to *limit* messages with id < before_id, in chronological order."""
    with Session(_get_engine()) as session:
        stmt = (
            select(Conversation)
            .where(Conversation.id < before_id)
            .order_by(Conversation.id.desc())
            .limit(limit)
        )
        if mode:
            stmt = stmt.where(Conversation.mode == mode)
        rows = session.exec(stmt).all()
    return [r.model_dump() for r in reversed(rows)]


def get_message_count(mode: str | None = None) -> int:
    """Return the total number of stored messages, optionally filtered by mode."""
    with Session(_get_engine()) as session:
        stmt = select(sa.func.count()).select_from(Conversation)
        if mode:
            stmt = stmt.where(Conversation.mode == mode)
        return session.execute(stmt).scalar() or 0


def search_messages(query: str, limit: int = 20, mode: str | None = None) -> list[dict]:
    """Case-insensitive substring search. Returns newest-first."""
    with Session(_get_engine()) as session:
        stmt = (
            select(Conversation)
            .where(Conversation.content.ilike(f"%{query}%"))
            .order_by(Conversation.id.desc())
            .limit(limit)
        )
        if mode:
            stmt = stmt.where(Conversation.mode == mode)
        rows = session.exec(stmt).all()
    return [r.model_dump() for r in rows]


# ── Memories ──────────────────────────────────────────────────────────────────


def save_memory(category: str, content: str) -> str:
    """Persist a memory. Returns a status string for the tool result."""
    try:
        with Session(_get_engine()) as session:
            stmt = sqlite_insert(Memory).values(category=category, content=content)
            stmt = stmt.on_conflict_do_nothing(index_elements=["content"])
            session.execute(stmt)
            session.commit()
        return "Memory saved."
    except Exception as exc:
        return f"Error: {exc}"


def get_all_memories() -> list[dict]:
    with Session(_get_engine()) as session:
        rows = session.exec(select(Memory).order_by(Memory.created_at)).all()
    return [r.model_dump() for r in rows]


# ── Calendar ──────────────────────────────────────────────────────────────────


def get_calendar_prefs() -> dict:
    with Session(_get_engine()) as session:
        row = session.get(CalendarPref, 1)
    if row is None:
        return {"blocked_days": [], "races": []}
    return {
        "blocked_days": json.loads(row.blocked_days),
        "races": json.loads(row.races),
    }


def save_calendar_prefs(blocked_days: list, races: list) -> None:
    with Session(_get_engine()) as session:
        stmt = sqlite_insert(CalendarPref).values(
            id=1,
            blocked_days=json.dumps(blocked_days),
            races=json.dumps(races),
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["id"],
            set_={
                "blocked_days": json.dumps(blocked_days),
                "races": json.dumps(races),
            },
        )
        session.execute(stmt)
        session.commit()


def get_training_plan(start_date: str | None = None, end_date: str | None = None) -> list[dict]:
    with Session(_get_engine()) as session:
        stmt = select(TrainingPlan).order_by(TrainingPlan.date)
        if start_date and end_date:
            stmt = stmt.where(TrainingPlan.date.between(start_date, end_date))
        rows = session.exec(stmt).all()
    return [r.model_dump() for r in rows]


def save_planned_workout(
    date: str,
    workout_type: str,
    description: str | None,
    distance_km: float | None,
    elevation_m: float | None,
    duration_min: int | None,
    intensity: str | None,
) -> None:
    """Upsert a user-entered planned workout."""
    with Session(_get_engine()) as session:
        stmt = sqlite_insert(TrainingPlan).values(
            date=date,
            workout_type=workout_type,
            description=description,
            distance_km=distance_km,
            elevation_m=elevation_m,
            duration_min=duration_min,
            intensity=intensity,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["date"],
            set_={
                "workout_type": workout_type,
                "description": description,
                "distance_km": distance_km,
                "elevation_m": elevation_m,
                "duration_min": duration_min,
                "intensity": intensity,
                "nutrition_json": None,
                "created_at": sa.text("datetime('now')"),
            },
        )
        session.execute(stmt)
        session.commit()


def delete_planned_workout(date: str) -> None:
    with Session(_get_engine()) as session:
        row = session.get(TrainingPlan, date)
        if row:
            session.delete(row)
            session.commit()


def save_workout_nutrition(date: str, nutrition: dict) -> None:
    with Session(_get_engine()) as session:
        row = session.get(TrainingPlan, date)
        if row:
            row.nutrition_json = json.dumps(nutrition)
            session.add(row)
            session.commit()


def get_upcoming_planned_workouts(days: int = 14) -> list[dict]:
    """Return planned workouts from today through the next `days` days."""
    today = date_cls.today().isoformat()
    end = (date_cls.today() + timedelta(days=days)).isoformat()
    with Session(_get_engine()) as session:
        stmt = (
            select(TrainingPlan)
            .where(TrainingPlan.date >= today, TrainingPlan.date <= end)
            .order_by(TrainingPlan.date)
        )
        rows = session.exec(stmt).all()
    return [r.model_dump() for r in rows]
