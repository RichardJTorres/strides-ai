"""The calendar taxonomy, defined once.

An entry has a *kind* (what sort of thing is on the calendar). Only ``workout`` and ``race``
entries carry detail rows. A workout has a ``workout_type`` (the activity); a race has a
``sport``. Everything that used to hand-copy these lists (compliance, tool schemas, structure
rules, the frontend constants) imports from here or reads ``taxonomy()``.
"""

from __future__ import annotations

KIND_WORKOUT = "workout"
KIND_RACE = "race"
KIND_REST = "rest"
KIND_TRAVEL = "travel"
KIND_OTHER = "other"
KINDS = (KIND_WORKOUT, KIND_RACE, KIND_REST, KIND_TRAVEL, KIND_OTHER)
KINDS_WITH_DETAIL = (KIND_WORKOUT, KIND_RACE)

RUN_WORKOUT_TYPES = frozenset({"Easy Run", "Long Run", "Tempo Run"})
RIDE_WORKOUT_TYPES = frozenset({"Easy Ride", "Long Ride", "Tempo Ride", "Indoor Ride"})
OTHER_WORKOUT_TYPES = ("Intervals", "Cross-Training", "Yoga")
# Workouts that cannot be checked against activity data.
UNSCORED_WORKOUT_TYPES = frozenset({"Yoga"})

RACE_SPORTS = ("run", "ride", "other")
RACE_PRIORITIES = ("A", "B", "C")

# What the pre-entry model called a race / rest, kept so prompts and the UI read the same.
LEGACY_RACE_TYPE_BY_SPORT = {"run": "Running Race", "ride": "Cycling Race", "other": "Race"}
LEGACY_REST_TYPE = "Rest"
_SPORT_BY_LEGACY_RACE_TYPE = {v: k for k, v in LEGACY_RACE_TYPE_BY_SPORT.items()}
LEGACY_RACE_TYPES = frozenset(_SPORT_BY_LEGACY_RACE_TYPE)

# The strings older consumers see (see display_type): a race reads as its sport's race type.
RUN_DISPLAY_TYPES = RUN_WORKOUT_TYPES | {LEGACY_RACE_TYPE_BY_SPORT["run"]}
RIDE_DISPLAY_TYPES = RIDE_WORKOUT_TYPES | {LEGACY_RACE_TYPE_BY_SPORT["ride"]}
UNSCORED_DISPLAY_TYPES = UNSCORED_WORKOUT_TYPES | {LEGACY_REST_TYPE}

ROUTE_CAPABLE_WORKOUT_TYPES = RUN_WORKOUT_TYPES | RIDE_WORKOUT_TYPES
STRUCTURE_CAPABLE_WORKOUT_TYPES = RIDE_WORKOUT_TYPES
WORKOUT_TYPES = tuple(
    sorted(RUN_WORKOUT_TYPES) + sorted(RIDE_WORKOUT_TYPES) + list(OTHER_WORKOUT_TYPES)
)


def is_valid_workout_type(workout_type: str | None) -> bool:
    return workout_type in WORKOUT_TYPES


def scored_group(workout_type: str | None) -> str | None:
    """'run' | 'ride' | 'ambiguous' for a scored workout type, None when it is never scored."""
    if workout_type in UNSCORED_WORKOUT_TYPES:
        return None
    if workout_type in RUN_WORKOUT_TYPES:
        return "run"
    if workout_type in RIDE_WORKOUT_TYPES:
        return "ride"
    return "ambiguous"


def race_sport_for_legacy_type(workout_type: str | None) -> str | None:
    """'Running Race' -> 'run', ... ; None when the string is not a legacy race type."""
    return _SPORT_BY_LEGACY_RACE_TYPE.get(workout_type or "")


def display_type(kind: str, workout_type: str | None, sport: str | None) -> str:
    """The single string older consumers (prompts, UI chips) use for an entry."""
    if kind == KIND_RACE:
        return LEGACY_RACE_TYPE_BY_SPORT.get(sport or "other", "Race")
    if kind == KIND_REST:
        return LEGACY_REST_TYPE
    if kind == KIND_WORKOUT:
        return workout_type or "Workout"
    return kind.capitalize()


def taxonomy() -> dict:
    """Served at GET /api/calendar/kinds so the frontend never re-declares the lists."""
    return {
        "kinds": list(KINDS),
        "workout_types": {
            "run": sorted(RUN_WORKOUT_TYPES),
            "ride": sorted(RIDE_WORKOUT_TYPES),
            "other": list(OTHER_WORKOUT_TYPES),
        },
        "route_capable": sorted(ROUTE_CAPABLE_WORKOUT_TYPES),
        "structure_capable": sorted(STRUCTURE_CAPABLE_WORKOUT_TYPES),
        "unscored_workout_types": sorted(UNSCORED_WORKOUT_TYPES),
        "race_sports": list(RACE_SPORTS),
        "race_priorities": list(RACE_PRIORITIES),
    }


def parse_goal_time(text) -> int | None:
    """Strict ``H:MM:SS`` / ``MM:SS`` -> seconds; anything else (``sub 4``, ``3h30``) is None."""
    import re

    m = re.match(r"^(?:(\d{1,2}):)?(\d{1,2}):(\d{2})$", str(text or "").strip())
    if not m:
        return None
    h, mnt, sec = int(m.group(1) or 0), int(m.group(2)), int(m.group(3))
    if sec > 59 or (m.group(1) is not None and mnt > 59):
        return None
    return h * 3600 + mnt * 60 + sec
