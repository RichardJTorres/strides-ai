"""Pure plan-vs-actual compliance scoring.

No DB/session access. Every function takes `today: date` explicitly — never calls
date.today() internally — mirroring strides_ai/analytics/cardio.py's determinism rule.

The workout-type taxonomy below is a second, independently-maintained copy of the sport
groupings web/src/pages/Calendar.tsx uses for its planner dropdown (WORKOUT_TYPE_GROUPS /
NO_DISTANCE_WORKOUT_TYPES). See LIMITATIONS below for why, and the drift mitigation.

LIMITATIONS (v1):
- workout_type taxonomy is duplicated with web/src/pages/Calendar.tsx's WORKOUT_TYPE_GROUPS /
  NO_DISTANCE_WORKOUT_TYPES. If they drift, a newly-added frontend type falls back to
  SportGroup.AMBIGUOUS here (presence-only match) rather than crashing or misclassifying into
  the wrong sport bucket — safe but less precise. No shared-constants mechanism exists across
  the TS/Python boundary; cross-reference comments in both files are the only guard.
- duration_min is never scored. A duration-only plan (distance_km=None) degrades to
  presence-only matching once a same-sport activity exists, however short.
- Activity.date for HEVY-sourced rows is stamped in UTC (strides_ai/hevy_sync.py), not local
  time, while Strava/TrainingPlan dates are local. Exact-string-date matching can be off by one
  day near local midnight for lifting activities. Pre-existing bug, not fixed by this feature.
- Matching is exact-date-string only — no "logged a day late" fuzzy matching.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Optional

from .activity_types import CYCLE_TYPES, RUN_TYPES
from .units import DEFAULT_UNIT_SYSTEM, Quantity, UnitSystem, format_value

# Mirrors web/src/pages/Calendar.tsx's WORKOUT_TYPE_GROUPS — keep in sync; drift falls back to
# SportGroup.AMBIGUOUS (presence-only matching), never crashes or misclassifies.
RUN_WORKOUT_TYPES = frozenset({"Easy Run", "Long Run", "Tempo Run", "Running Race"})
RIDE_WORKOUT_TYPES = frozenset(
    {"Easy Ride", "Long Ride", "Tempo Ride", "Indoor Ride", "Cycling Race"}
)
# Mirrors web/src/pages/Calendar.tsx's NO_DISTANCE_WORKOUT_TYPES.
UNSCORED_WORKOUT_TYPES = frozenset({"Rest", "Yoga"})

# actual_km >= DISTANCE_SHORTFALL_TOLERANCE * planned_km => COMPLETED (boundary inclusive).
# No upper bound — overshooting a planned distance is never penalized.
DISTANCE_SHORTFALL_TOLERANCE = 0.8


class ComplianceStatus(str, Enum):
    COMPLETED = (
        "completed"  # matching-sport activity found, distance within tolerance (or no target)
    )
    MODIFIED = "modified"  # matching-sport activity found, distance well short of plan
    MISSED = "missed"  # plan date is strictly in the past, no matching activity found
    UPCOMING = "upcoming"  # plan date is today or in the future — not yet scorable
    UNSCORED = "unscored"  # Rest/Yoga — not verifiable against activity data at all


class SportGroup(str, Enum):
    RUN = "run"
    RIDE = "ride"
    AMBIGUOUS = "ambiguous"
    UNSCORED = "unscored"


@dataclass(frozen=True)
class PlannedWorkout:
    date: date
    workout_type: str
    distance_km: Optional[float]


@dataclass(frozen=True)
class ComplianceActivity:
    id: int
    date: date
    sport_type: Optional[str]
    distance_m: Optional[float]


@dataclass(frozen=True)
class DayCompliance:
    date: date
    workout_type: str
    status: ComplianceStatus
    planned_distance_km: Optional[float]
    actual_distance_km: Optional[float]  # None only if no qualifying activity recorded any distance
    matched_activity_id: Optional[int]
    note: str


@dataclass(frozen=True)
class ComplianceSummary:
    total_scored: int  # completed+modified+missed (excludes unscored/upcoming)
    completed: int
    modified: int
    missed: int
    unscored: int
    upcoming: int
    consistency_pct: Optional[
        float
    ]  # (completed+modified)/total_scored — "did something on plan days"
    on_target_pct: Optional[float]  # completed/total_scored — "trained as planned"


def classify_workout_type(workout_type: Optional[str]) -> SportGroup:
    if workout_type in UNSCORED_WORKOUT_TYPES:
        return SportGroup.UNSCORED
    if workout_type in RUN_WORKOUT_TYPES:
        return SportGroup.RUN
    if workout_type in RIDE_WORKOUT_TYPES:
        return SportGroup.RIDE
    return SportGroup.AMBIGUOUS  # None and unrecognized strings land here — never raises


def _qualifying(group: SportGroup, same_day: list[ComplianceActivity]) -> list[ComplianceActivity]:
    if group is SportGroup.RUN:
        return [a for a in same_day if a.sport_type in RUN_TYPES]
    if group is SportGroup.RIDE:
        return [a for a in same_day if a.sport_type in CYCLE_TYPES]
    return list(same_day)  # AMBIGUOUS and UNSCORED: presence of anything counts


def _pick_matched(qualifying: list[ComplianceActivity]) -> Optional[ComplianceActivity]:
    """Deterministic, documented, arbitrary tie-break: largest distance_m wins; ties (including
    all-None, e.g. two lifts on an ambiguous day) broken by lowest id."""
    if not qualifying:
        return None
    return sorted(qualifying, key=lambda a: (-(a.distance_m or 0.0), a.id))[0]


def _summed_km(qualifying: list[ComplianceActivity]) -> Optional[float]:
    """None iff NONE of the qualifying activities recorded a distance — distinguishes
    'no distance data available' from a genuine zero-distance activity."""
    distances = [a.distance_m for a in qualifying if a.distance_m is not None]
    return sum(distances) / 1000 if distances else None


def compute_day_compliance(
    planned: PlannedWorkout,
    same_day_activities: list[ComplianceActivity],
    today: date,
    units: UnitSystem = DEFAULT_UNIT_SYSTEM,
) -> DayCompliance:
    group = classify_workout_type(planned.workout_type)
    qualifying = _qualifying(group, same_day_activities)
    matched = _pick_matched(qualifying)
    has_target = planned.distance_km is not None and planned.distance_km > 0

    def day(status: ComplianceStatus, actual_km: Optional[float], note: str) -> DayCompliance:
        return DayCompliance(
            date=planned.date,
            workout_type=planned.workout_type,
            status=status,
            planned_distance_km=planned.distance_km,
            actual_distance_km=actual_km,
            matched_activity_id=matched.id if matched else None,
            note=note,
        )

    # 1. UNSCORED — unconditional, regardless of date or match.
    if group is SportGroup.UNSCORED:
        actual_km = _summed_km(qualifying)
        note = (
            "An activity was logged this day but is not scored against a rest/yoga plan"
            if matched
            else "Rest/Yoga-type workout — not verifiable against activity data"
        )
        return day(ComplianceStatus.UNSCORED, actual_km, note)

    # 2. AMBIGUOUS group — presence only, no distance tolerance (no sport-specific target exists).
    if group is SportGroup.AMBIGUOUS and matched is not None:
        return day(
            ComplianceStatus.COMPLETED,
            _summed_km(qualifying),
            "Activity logged this day (sport-ambiguous workout type — presence only)",
        )

    # 3. RUN/RIDE with a qualifying same-sport activity.
    if group in (SportGroup.RUN, SportGroup.RIDE) and qualifying:
        actual_km = _summed_km(qualifying)
        if actual_km is None:
            status = ComplianceStatus.MODIFIED if has_target else ComplianceStatus.COMPLETED
            note = "Matching-sport activity found but it recorded no distance data" + (
                " — treated as a shortfall" if has_target else "; no distance target to compare"
            )
        elif not has_target or actual_km >= DISTANCE_SHORTFALL_TOLERANCE * planned.distance_km:
            status = ComplianceStatus.COMPLETED
            note = "Matching-sport activity found" + (
                "" if has_target else "; no distance target to compare"
            )
        else:
            status = ComplianceStatus.MODIFIED
            actual = format_value(actual_km * 1000, Quantity.DISTANCE, units, decimals=1)
            target = format_value(planned.distance_km * 1000, Quantity.DISTANCE, units, decimals=1)
            note = (
                f"Matching-sport activity found but {actual} vs planned {target} "
                f"(below {int(DISTANCE_SHORTFALL_TOLERANCE * 100)}% target)"
            )
        return day(status, actual_km, note)

    # 4. No match of any kind — resolve by date. Today counts as not-yet-due.
    if planned.date >= today:
        return day(ComplianceStatus.UPCOMING, None, "Not yet due")
    return day(ComplianceStatus.MISSED, None, "No matching activity found and the date has passed")


def compute_range_compliance(
    planned_workouts: list[PlannedWorkout],
    activities: list[ComplianceActivity],
    today: date,
    units: UnitSystem = DEFAULT_UNIT_SYSTEM,
) -> list[DayCompliance]:
    """One DayCompliance per input PlannedWorkout. Does not deduplicate by date — correctness
    for 'at most one planned workout per date' is guaranteed upstream by training_plan.date
    being the primary key (strides_ai/db/models.py), not enforced here; if ever violated,
    duplicates produce independent, non-deduplicated output rows rather than crashing."""
    by_date: dict[date, list[ComplianceActivity]] = defaultdict(list)
    for a in activities:
        by_date[a.date].append(a)
    return [
        compute_day_compliance(p, by_date.get(p.date, []), today, units) for p in planned_workouts
    ]


def summarize_compliance(days: list[DayCompliance]) -> ComplianceSummary:
    completed = sum(d.status is ComplianceStatus.COMPLETED for d in days)
    modified = sum(d.status is ComplianceStatus.MODIFIED for d in days)
    missed = sum(d.status is ComplianceStatus.MISSED for d in days)
    unscored = sum(d.status is ComplianceStatus.UNSCORED for d in days)
    upcoming = sum(d.status is ComplianceStatus.UPCOMING for d in days)
    total_scored = completed + modified + missed
    consistency_pct = (
        round(100 * (completed + modified) / total_scored, 1) if total_scored else None
    )
    on_target_pct = round(100 * completed / total_scored, 1) if total_scored else None
    return ComplianceSummary(
        total_scored=total_scored,
        completed=completed,
        modified=modified,
        missed=missed,
        unscored=unscored,
        upcoming=upcoming,
        consistency_pct=consistency_pct,
        on_target_pct=on_target_pct,
    )


# ── Boundary adapters: the only functions here that know TrainingPlan/Activity.model_dump() shapes ──


def planned_workouts_from_rows(rows: list[dict]) -> list[PlannedWorkout]:
    """Drops rows with an unparseable/missing date (defensive only — training_plan.date is
    always 'YYYY-MM-DD' in practice)."""
    out = []
    for row in rows:
        try:
            d = date.fromisoformat(row.get("date") or "")
        except ValueError:
            continue
        out.append(
            PlannedWorkout(
                date=d,
                workout_type=row.get("workout_type") or "",
                distance_km=row.get("distance_km"),
            )
        )
    return out


def compliance_activities_from_rows(rows: list[dict]) -> list[ComplianceActivity]:
    """Drops rows with an unparseable/empty date — e.g. a HEVY workout with no start_time,
    which hevy_sync._transform_workout stores as date=""."""
    out = []
    for row in rows:
        try:
            d = date.fromisoformat(row.get("date") or "")
        except ValueError:
            continue
        out.append(
            ComplianceActivity(
                id=row["id"],
                date=d,
                sport_type=row.get("sport_type"),
                distance_m=row.get("distance_m"),
            )
        )
    return out
