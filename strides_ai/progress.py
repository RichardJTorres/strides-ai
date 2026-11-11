"""Progress: the weekly plan streak, this week's quests, and personal records.

Pure: no DB access, `today` is passed explicitly (same rule as compliance.py). Everything is
derived on read from plan rows and activity rows; nothing is stored. Not mode-scoped: the plan is
shared across modes, and each record carries the `sport` it belongs to.

Weeks are Monday-Sunday (analytics.aggregation.monday_of), like every other weekly figure.

Streak
  done = completed + modified ("shortened" still counts as showing up); Rest/Yoga are unscored.
  A week is HIT when done >= 1 and missed <= MAX_MISSES. A week with no scored days (no plan, or
  only Rest/Yoga) is PAUSED: it neither extends nor breaks the streak, but more than
  MAX_PAUSED_WEEKS paused weeks in a row end it, so an abandoned plan is not a current streak.
  The in-progress week never counts and never breaks it; `this_week` reports where it is heading.

Quests (current week, from that week's plan; capped at MAX_QUESTS, rest days dropped first)
  long     one per planned Long Run / Long Ride
  quality  one per planned Tempo Run / Tempo Ride / Intervals
  rest     one per planned Rest day: missed if a run or ride with distance was logged that day
           (a lift or a walk does not break a rest day), else done once the day has passed.

Records (per sport)
  A sport has records only once it has MIN_ACTIVITIES qualifying activities and the earliest is
  at least RECORD_MIN_HISTORY_DAYS old, so the first few activities are not all "records".
  Ties go to the earliest date, then the lowest id, so repeating a best is never a new record.
  Week records only consider completed weeks. No pace records: Strava best efforts are not
  fetched, and a whole-activity average would overstate or understate a true best effort.
"""

from collections import defaultdict
from datetime import date, timedelta
from typing import Callable, Literal, Optional

from pydantic import BaseModel

from .activity_types import CYCLE_TYPES, LIFT_TYPES, RUN_TYPES
from .analytics.aggregation import monday_of
from .charts_lifting import _iter_working_sets, compute_one_rm_progression
from .compliance import ComplianceStatus, DayCompliance, compliance_for_range
from .hevy_analysis import estimate_1rm
from .units import Quantity, UnitSystem, format_value

MAX_MISSES = 1  # scored plan days a week may miss and still count
MAX_PAUSED_WEEKS = 2  # consecutive unscored weeks a streak survives
MAX_QUESTS = 4
MIN_ACTIVITIES = 6  # per sport, before it has records
RECORD_MIN_HISTORY_DAYS = 28
RECORD_FRESH_DAYS = 14  # a record set within this many days is flagged "new"
E1RM_EXERCISES = 6  # most-trained lifts that get an estimated-1RM record

LONG_WORKOUT_TYPES = frozenset({"Long Run", "Long Ride"})
QUALITY_WORKOUT_TYPES = frozenset({"Tempo Run", "Tempo Ride", "Intervals"})

_DONE = (ComplianceStatus.COMPLETED, ComplianceStatus.MODIFIED)


# ── Payload ─────────────────────────────────────────────────────────────────────


class RecordPrev(BaseModel):
    value: float
    formatted: str
    date: str


class Record(BaseModel):
    id: str  # "run.longest", "lift.e1rm:Bench Press"
    sport: Literal["run", "ride", "lift"]
    label: str
    value: float  # SI: meters or kilograms
    formatted: str  # in the athlete's units
    date: str  # the activity's date; the week's Monday for week records
    activity_id: Optional[int]  # None for week records
    is_new: bool
    previous: Optional[RecordPrev]  # the best before `date`; None when this is the first


class Quest(BaseModel):
    id: str  # f"{kind}:{date}"
    kind: Literal["long", "quality", "rest"]
    label: str
    date: str
    status: Literal["done", "partial", "pending", "missed"]
    activity_id: Optional[int]


class ThisWeek(BaseModel):
    done: int
    missed: int
    upcoming: int
    status: Literal["hit", "on_track", "at_risk", "lost", "no_plan"]


class Streak(BaseModel):
    weeks: int
    best_weeks: int
    max_misses: int
    this_week: ThisWeek


class ProgressPayload(BaseModel):
    as_of: str
    unit_system: str
    week_start: str  # Monday of the current week
    streak: Streak
    quests: list[Quest]
    records: list[Record]


# ── Streak ──────────────────────────────────────────────────────────────────────


def _counts(days: list[DayCompliance]) -> tuple[int, int, int]:
    """(done, missed, upcoming) — unscored days are in none of them."""
    return (
        sum(d.status in _DONE for d in days),
        sum(d.status is ComplianceStatus.MISSED for d in days),
        sum(d.status is ComplianceStatus.UPCOMING for d in days),
    )


def _week_hit(days: list[DayCompliance]) -> Optional[bool]:
    """True/False for a week with scored days; None when it has none (paused)."""
    done, missed, _ = _counts(days)
    if done + missed == 0:
        return None
    return done >= 1 and missed <= MAX_MISSES


def streak_weeks(days: list[DayCompliance], today: date) -> tuple[int, int]:
    """(current, best) streak in weeks, over every completed week the days cover."""
    by_week: dict[date, list[DayCompliance]] = defaultdict(list)
    for d in days:
        by_week[monday_of(d.date)].append(d)
    last = monday_of(today) - timedelta(weeks=1)
    if not by_week or min(by_week) > last:
        return 0, 0
    current = best = paused = 0
    wk = min(by_week)
    while wk <= last:
        hit = _week_hit(by_week.get(wk, []))
        if hit is None:
            paused += 1
            if paused > MAX_PAUSED_WEEKS:
                current = 0
        else:
            paused = 0
            current = current + 1 if hit else 0
            best = max(best, current)
        wk += timedelta(weeks=1)
    return current, best


def compute_streak(days: list[DayCompliance], today: date) -> int:
    """Weeks in the current streak."""
    return streak_weeks(days, today)[0]


def this_week(days: list[DayCompliance]) -> ThisWeek:
    """Where the in-progress week stands. `hit` means secured: even if every remaining day were
    missed the week would still count. `lost` means it can no longer count."""
    done, missed, upcoming = _counts(days)
    if done + missed + upcoming == 0:
        status = "no_plan"
    elif missed > MAX_MISSES or done + upcoming == 0:
        status = "lost"
    elif done >= 1 and missed + upcoming <= MAX_MISSES:
        status = "hit"
    elif missed == 0:
        status = "on_track"
    else:
        status = "at_risk"
    return ThisWeek(done=done, missed=missed, upcoming=upcoming, status=status)


# ── Weekly quests ───────────────────────────────────────────────────────────────

_QUEST_STATUS = {
    ComplianceStatus.COMPLETED: "done",
    ComplianceStatus.MODIFIED: "partial",
    ComplianceStatus.UPCOMING: "pending",
    ComplianceStatus.MISSED: "missed",
}


def build_week_quests(
    days: list[DayCompliance], today: date, cardio_dates: frozenset[date] = frozenset()
) -> list[Quest]:
    """Quests for the days of one week (long, then quality, then rest; each by date).
    `cardio_dates` are the days with a run or ride that covered distance."""
    by_kind: dict[str, list[Quest]] = {"long": [], "quality": [], "rest": []}
    for d in sorted(days, key=lambda d: d.date):
        activity_id = d.matched_activity_id
        if d.workout_type in LONG_WORKOUT_TYPES:
            kind, label, status = "long", d.workout_type, _QUEST_STATUS.get(d.status)
        elif d.workout_type in QUALITY_WORKOUT_TYPES:
            kind, label, status = "quality", d.workout_type, _QUEST_STATUS.get(d.status)
        elif d.workout_type == "Rest":
            kind, label, activity_id = "rest", "Rest day", None
            if d.date in cardio_dates:
                status = "missed"
            else:
                status = "pending" if d.date >= today else "done"
        else:
            continue
        if status is None:
            continue
        by_kind[kind].append(
            Quest(
                id=f"{kind}:{d.date.isoformat()}",
                kind=kind,
                label=label,
                date=d.date.isoformat(),
                status=status,
                activity_id=activity_id,
            )
        )
    return [q for kind in ("long", "quality", "rest") for q in by_kind[kind]][:MAX_QUESTS]


# ── Personal records ────────────────────────────────────────────────────────────

# One scored thing that can hold a record: (date, activity id or None for a week, SI value).
_Entry = tuple[date, Optional[int], float]


def _parse_date(row: dict) -> Optional[date]:
    try:
        return date.fromisoformat(row.get("date") or "")
    except (TypeError, ValueError):
        return None


def _positive(value) -> Optional[float]:
    try:
        return float(value) if value is not None and float(value) > 0 else None
    except (TypeError, ValueError):
        return None


def _best(entries: list[_Entry]) -> Optional[_Entry]:
    """Highest value; ties to the earliest date, then the lowest id."""
    return min(entries, key=lambda e: (-e[2], e[0], e[1] or 0)) if entries else None


def _record(
    record_id: str,
    sport: str,
    label: str,
    entries: list[_Entry],
    fmt: Callable[[float], str],
    today: date,
    week: bool = False,
) -> Optional[Record]:
    top = _best(entries)
    if top is None:
        return None
    when, activity_id, value = top
    prev = _best([e for e in entries if e[0] < when])
    # A week is "new" for RECORD_FRESH_DAYS after it ends (its Sunday), not after its Monday.
    achieved = when + timedelta(days=6) if week else when
    return Record(
        id=record_id,
        sport=sport,
        label=label,
        value=value,
        formatted=fmt(value),
        date=when.isoformat(),
        activity_id=activity_id,
        is_new=(today - achieved).days < RECORD_FRESH_DAYS,
        previous=(
            RecordPrev(value=prev[2], formatted=fmt(prev[2]), date=prev[0].isoformat())
            if prev
            else None
        ),
    )


def _eligible(dates: list[date], today: date) -> bool:
    return len(dates) >= MIN_ACTIVITIES and (today - min(dates)).days >= RECORD_MIN_HISTORY_DAYS


def _weekly(entries: list[_Entry], today: date) -> list[_Entry]:
    """Per-week totals for completed weeks, dated by the week's Monday."""
    this_monday = monday_of(today)
    totals: dict[date, float] = defaultdict(float)
    for when, _, value in entries:
        if monday_of(when) < this_monday:
            totals[monday_of(when)] += value
    return [(wk, None, total) for wk, total in totals.items()]


def _cardio_records(
    rows: list[dict], sport: str, noun: str, types: frozenset, units: UnitSystem, today: date
) -> list[Record]:
    distance: list[_Entry] = []
    climb: list[_Entry] = []
    for row in rows:
        when = _parse_date(row)
        metres = _positive(row.get("distance_m"))
        if when is None or row.get("sport_type") not in types or metres is None:
            continue
        distance.append((when, row["id"], metres))
        gain = _positive(row.get("elevation_gain_m"))
        if gain is not None:
            climb.append((when, row["id"], gain))
    if not _eligible([e[0] for e in distance], today):
        return []

    def dist(v: float) -> str:
        return format_value(v, Quantity.DISTANCE, units, decimals=1)

    def elev(v: float) -> str:
        return format_value(v, Quantity.ELEVATION, units, decimals=0)

    specs = [
        (f"{sport}.longest", f"Longest {noun}", distance, dist, False),
        (f"{sport}.most_climb", f"Most climbing in a {noun}", climb, elev, False),
        (f"{sport}.biggest_week", f"Biggest {noun} week", _weekly(distance, today), dist, True),
    ]
    if sport == "ride":
        specs.append(
            (
                f"{sport}.biggest_week_climb",
                "Most climbing in a week",
                _weekly(climb, today),
                elev,
                True,
            )
        )
    records = [_record(i, sport, label, e, fmt, today, week) for i, label, e, fmt, week in specs]
    return [r for r in records if r is not None]


def _lift_records(rows: list[dict], units: UnitSystem, today: date) -> list[Record]:
    lifts = [
        (when, row)
        for row in rows
        if row.get("sport_type") in LIFT_TYPES and (when := _parse_date(row)) is not None
    ]
    if not _eligible([when for when, _ in lifts], today):
        return []

    def mass(v: float) -> str:
        return format_value(v, Quantity.MASS, units, decimals=1)

    # The same most-trained exercises the 1RM chart shows, with the same per-set estimate.
    titles = compute_one_rm_progression([row for _, row in lifts], top_n=E1RM_EXERCISES)[
        "exercises"
    ]
    e1rm: dict[str, list[_Entry]] = {t: [] for t in titles}
    volume: list[_Entry] = []
    for when, row in lifts:
        best: dict[str, float] = {}
        for title, _muscle, s in _iter_working_sets(row):
            if title not in e1rm:
                continue
            est = estimate_1rm(float(s.get("weight_kg") or 0.0), int(s.get("reps") or 0))
            if est is not None and est > best.get(title, 0.0):
                best[title] = est
        for title, est in best.items():
            e1rm[title].append((when, row["id"], round(est, 1)))
        total = _positive(row.get("total_volume_kg"))
        if total is not None:
            volume.append((when, row["id"], total))

    records = [
        _record(f"lift.e1rm:{t}", "lift", f"{t} (est. 1RM)", e1rm[t], mass, today) for t in titles
    ]
    records.append(
        _record("lift.session_volume", "lift", "Biggest session volume", volume, mass, today)
    )
    return [r for r in records if r is not None]


def build_records(rows: list[dict], units: UnitSystem, today: date) -> list[Record]:
    """Records for every sport that has enough history: runs, then rides, then lifts."""
    return (
        _cardio_records(rows, "run", "run", RUN_TYPES, units, today)
        + _cardio_records(rows, "ride", "ride", CYCLE_TYPES, units, today)
        + _lift_records(rows, units, today)
    )


# ── Orchestrator ────────────────────────────────────────────────────────────────


def build_progress(
    plan_rows: list[dict], activity_rows: list[dict], today: date, units: UnitSystem
) -> ProgressPayload:
    """`activity_rows` must be ALL activities (see compliance.compliance_for_range)."""
    units = UnitSystem.parse(units)
    this_monday = monday_of(today)
    week_end = this_monday + timedelta(days=6)
    days = compliance_for_range(plan_rows, activity_rows, date.min, week_end, today, units)
    week_days = [d for d in days if d.date >= this_monday]
    cardio_dates = frozenset(
        when
        for row in activity_rows
        if row.get("sport_type") in RUN_TYPES | CYCLE_TYPES
        and _positive(row.get("distance_m")) is not None
        and (when := _parse_date(row)) is not None
    )
    current, best = streak_weeks(days, today)
    return ProgressPayload(
        as_of=today.isoformat(),
        unit_system=units.value,
        week_start=this_monday.isoformat(),
        streak=Streak(
            weeks=current, best_weeks=best, max_misses=MAX_MISSES, this_week=this_week(week_days)
        ),
        quests=build_week_quests(week_days, today, cardio_dates),
        records=build_records(activity_rows, units, today),
    )
