"""Activity CRUD operations."""

import json
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlmodel import Session, select

from .models import Activity, RUN_TYPES, CYCLE_TYPES, LIFT_TYPES
from ..modes import MODES


def get_latest_activity_date(session: Session) -> str | None:
    """Return the ISO date of the most recent stored activity, or None."""
    return session.execute(select(sa.func.max(Activity.date))).scalar()


def get_stored_ids(session: Session) -> set[int]:
    return set(session.execute(select(Activity.id)).scalars().all())


def upsert(session: Session, activity: dict[str, Any]) -> None:
    """Insert or replace an activity row derived from a Strava API response."""
    distance_m: float = activity.get("distance", 0)
    moving_time_s: int = activity.get("moving_time", 0)

    avg_pace_s_per_km = (
        moving_time_s / (distance_m / 1000) if distance_m > 0 and moving_time_s > 0 else None
    )

    sport = activity.get("sport_type", activity.get("type", ""))
    raw_cadence = activity.get("average_cadence")
    if raw_cadence is not None:
        avg_cadence = raw_cadence * 2 if sport in RUN_TYPES else raw_cadence
    else:
        avg_cadence = None

    values = {
        "id": activity["id"],
        "source": "strava",
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

    stmt = sqlite_insert(Activity).values(**values)
    stmt = stmt.on_conflict_do_update(
        index_elements=["id"],
        set_={k: v for k, v in values.items() if k != "id"},
    )
    session.execute(stmt)
    session.commit()


def upsert_hevy(session: Session, activity: dict[str, Any]) -> None:
    """Insert or replace an activity row derived from a HEVY workout."""
    values = {
        "id": activity["id"],
        "source": "hevy",
        "name": activity.get("name"),
        "date": activity.get("date"),
        "distance_m": None,
        "moving_time_s": activity.get("moving_time_s"),
        "elapsed_time_s": activity.get("elapsed_time_s"),
        "elevation_gain_m": None,
        "avg_pace_s_per_km": None,
        "avg_hr": None,
        "max_hr": None,
        "avg_cadence": None,
        "suffer_score": None,
        "perceived_exertion": activity.get("perceived_exertion"),
        "sport_type": "WeightTraining",
        "raw_json": activity.get("raw_json"),
        "external_id": activity.get("external_id"),
        "exercises_json": activity.get("exercises_json"),
        "total_volume_kg": activity.get("total_volume_kg"),
        "total_sets": activity.get("total_sets"),
    }

    stmt = sqlite_insert(Activity).values(**values)
    stmt = stmt.on_conflict_do_update(
        index_elements=["id"],
        set_={k: v for k, v in values.items() if k != "id"},
    )
    session.execute(stmt)
    session.commit()


def upsert_canonical(session: Session, activity) -> None:
    """Insert or replace an activity row from a CardioActivity or StrengthActivity."""
    from ..activity_types import CardioActivity, StrengthActivity

    if isinstance(activity, CardioActivity):
        values: dict = {
            "id": activity.id,
            "source": activity.source,
            "name": activity.name,
            "date": activity.date,
            "sport_type": activity.sport_type,
            "distance_m": activity.distance_m,
            "moving_time_s": activity.moving_time_s,
            "elapsed_time_s": activity.elapsed_time_s,
            "elevation_gain_m": activity.elevation_gain_m,
            "avg_pace_s_per_km": activity.avg_pace_s_per_km,
            "avg_hr": activity.avg_hr,
            "max_hr": activity.max_hr,
            "avg_cadence": activity.avg_cadence,
            "suffer_score": activity.suffer_score,
            "perceived_exertion": activity.perceived_exertion,
            "raw_json": activity.raw_json,
        }
    elif isinstance(activity, StrengthActivity):
        values = {
            "id": activity.id,
            "source": activity.source,
            "name": activity.name,
            "date": activity.date,
            "sport_type": activity.sport_type,
            "moving_time_s": activity.moving_time_s,
            "elapsed_time_s": activity.elapsed_time_s,
            "perceived_exertion": activity.perceived_exertion,
            "external_id": activity.external_id,
            "exercises_json": activity.exercises_json,
            "total_volume_kg": activity.total_volume_kg,
            "total_sets": activity.total_sets,
            "raw_json": activity.raw_json,
        }
    else:
        raise TypeError(f"Unknown canonical activity type: {type(activity)!r}")

    stmt = sqlite_insert(Activity).values(**values)
    stmt = stmt.on_conflict_do_update(
        index_elements=["id"],
        set_={k: v for k, v in values.items() if k != "id"},
    )
    session.execute(stmt)
    session.commit()


def get_all(session: Session) -> list[Activity]:
    """Return all activities ordered newest-first."""
    return session.exec(select(Activity).order_by(Activity.date.desc())).all()


def get_for_mode(session: Session, mode: str) -> list[Activity]:
    """Return activities filtered to the active mode, newest-first."""
    cfg = MODES.get(mode, MODES["running"])
    stmt = select(Activity).order_by(Activity.date.desc())
    if cfg.sport_types is not None:
        stmt = stmt.where(Activity.sport_type.in_(cfg.sport_types))
    return session.exec(stmt).all()


def get(session: Session, activity_id: int) -> Activity | None:
    """Return a single activity by ID, or None if not found."""
    return session.get(Activity, activity_id)


def update_analysis(session: Session, activity_id: int, metrics: dict) -> None:
    """Write computed analysis columns back to a single activity row."""
    if not metrics:
        return
    row = session.get(Activity, activity_id)
    if row is None:
        return
    for k, v in metrics.items():
        setattr(row, k, v)
    session.add(row)
    session.commit()


def get_pending_analysis(session: Session, limit: int = 10) -> list[Activity]:
    """Return up to *limit* activities where analysis_status is 'pending' or NULL."""
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
    return session.exec(stmt).all()


def mark_for_reanalysis(session: Session) -> int:
    """Queue every analysed Strava activity for a fresh analysis; return how many were queued.

    Used after an input the metrics depend on changes (max HR sets the HR zones). Activities
    with no stream data ('skipped') and HEVY sessions are left alone.
    """
    result = session.execute(
        sa.update(Activity)
        .where(
            Activity.analysis_status.in_(("done", "error")),
            sa.or_(Activity.source.is_(None), Activity.source != "hevy"),
        )
        .values(analysis_status="pending")
    )
    session.commit()
    return result.rowcount


def count_pending_analysis(session: Session) -> int:
    """How many activities are waiting for analysis (the same rows get_pending_analysis returns)."""
    stmt = select(sa.func.count()).where(
        sa.or_(Activity.analysis_status == "pending", Activity.analysis_status.is_(None))
    )
    return session.execute(stmt).scalar_one()


def renormalize_effort_efficiency(session: Session) -> None:
    """
    Re-score effort_efficiency_score with inverted min-max normalization over VALID rows only.
    Lower raw ratio (faster pace / lower HR) = more efficient = higher score.
    Formula: score = 100 * (max_raw - raw) / (max_raw - min_raw)

    Rows where pace per heartbeat means nothing (rides, hilly courses:
    decoupling.efficiency_validity) get a NULL score and do not stretch the scale; their raw
    value stays stored, as decoupling's does.
    """
    from ..decoupling import efficiency_validity

    rows = (
        session.execute(
            sa.text(
                "SELECT id, sport_type, effort_efficiency_raw, climb_m_per_km,"
                " elevation_gain_m, distance_m"
                " FROM activities WHERE effort_efficiency_raw IS NOT NULL"
            )
        )
        .mappings()
        .all()
    )
    valid = [r for r in rows if efficiency_validity(dict(r))[0]]
    invalid = [{"id": r["id"]} for r in rows if not efficiency_validity(dict(r))[0]]
    if invalid:
        session.execute(
            sa.text("UPDATE activities SET effort_efficiency_score = NULL WHERE id = :id"), invalid
        )
    if valid:
        raws = [r["effort_efficiency_raw"] for r in valid]
        low, high = min(raws), max(raws)
        session.execute(
            sa.text("UPDATE activities SET effort_efficiency_score = :score WHERE id = :id"),
            [
                {
                    "id": r["id"],
                    "score": (
                        50.0
                        if high == low
                        else round(100.0 * (high - r["effort_efficiency_raw"]) / (high - low), 2)
                    ),
                }
                for r in valid
            ],
        )
    session.commit()
