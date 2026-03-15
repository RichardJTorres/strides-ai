"""Activity CRUD operations."""

import json
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlmodel import Session, select

from .models import Activity, RUN_TYPES, CYCLE_TYPES


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


def get_all(session: Session) -> list[Activity]:
    """Return all activities ordered newest-first."""
    return session.exec(select(Activity).order_by(Activity.date.desc())).all()


def get_for_mode(session: Session, mode: str) -> list[Activity]:
    """Return activities filtered to the active mode, newest-first."""
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


def renormalize_effort_efficiency(session: Session) -> None:
    """
    Re-score effort_efficiency_score for all rows using inverted min-max normalization.
    Lower raw ratio (faster pace / lower HR) = more efficient = higher score.
    Formula: score = 100 * (max_raw - raw) / (max_raw - min_raw)
    """
    result = session.execute(
        sa.text(
            "SELECT MIN(effort_efficiency_raw), MAX(effort_efficiency_raw)"
            " FROM activities WHERE effort_efficiency_raw IS NOT NULL"
        )
    ).one()
    min_raw, max_raw = result

    if min_raw is None:
        return

    if min_raw == max_raw:
        session.execute(
            sa.text(
                "UPDATE activities SET effort_efficiency_score = 50.0"
                " WHERE effort_efficiency_raw IS NOT NULL"
            )
        )
    else:
        session.execute(
            sa.text(
                "UPDATE activities"
                " SET effort_efficiency_score = ROUND("
                "   100.0 * (:max_raw - effort_efficiency_raw) / (:max_raw - :min_raw), 2"
                " )"
                " WHERE effort_efficiency_raw IS NOT NULL"
            ),
            {"min_raw": min_raw, "max_raw": max_raw},
        )
    session.commit()
