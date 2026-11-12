"""Test helper: the old one-workout-per-date upsert, expressed as calendar entries."""

from strides_ai import db
from strides_ai.backends.base import _entry_kind


def save_planned_workout(
    date,
    workout_type,
    description=None,
    distance_km=None,
    elevation_m=None,
    duration_min=None,
    intensity=None,
    route_url=None,
    structure=None,
):
    """Replace whatever the date holds with one entry (old overwrite semantics, for fixtures)."""
    old = [r["id"] for r in db.get_training_plan(date, date)]
    kind, sport = _entry_kind({"workout_type": workout_type}, None)
    op = {"op": "create", "kind": kind, "date": date}
    if kind == "workout":
        op.update(
            workout_type=workout_type,
            objective=description,
            distance_km=distance_km,
            elevation_m=elevation_m,
            duration_min=duration_min,
            intensity=None if intensity == "rest" else intensity,
            route_url=route_url,
            structure=structure,
        )
    elif kind == "race":
        op.update(
            title=description or "Race",
            sport=sport or "other",
            distance_km=distance_km,
            elevation_m=elevation_m,
            route_url=route_url,
        )
    else:
        op["notes"] = description
    ops = [{"op": "delete", "id": i} for i in old] + [op]
    return db.apply_calendar_changes(ops)["created"][0]


def save_races(races):
    """Race list in the old prefs shape -> race entries."""
    for r in races:
        db.apply_calendar_changes(
            [
                {
                    "op": "create",
                    "kind": "race",
                    "date": r["date"],
                    "title": r.get("name"),
                    "sport": "other",
                }
            ]
        )
