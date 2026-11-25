"""One deterministic view of the athlete's training: current load, planned load and constraints.

Insights, the coach prompt, plan generation, the `update_training_plan` tool and the Calendar /
Analytics UIs all read this, so they cannot disagree about load thresholds, ramp rate or which
days are off limits.

Pure: no DB access, every function takes `today` explicitly (same rule as analytics/cardio.py).
Load is moving time in hours (`LOAD_UNIT`), matching `cardio.compute_atl_ctl`: one sport-neutral
unit, so a run hour and a ride hour add up and a long climbing day is not undercounted the way
distance undercounts it. Planned workouts count by `duration_min` (a race by its goal time).
"""

import math
import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

from .activity_types import CYCLE_TYPES, RUN_TYPES
from .analytics import cardio
from .analytics.adapters import to_cardio_analytics
from .analytics.aggregation import monday_of
from .compliance import SportGroup, classify_workout_type
from .kinds import display_type
from .units import DEFAULT_UNIT_SYSTEM, UnitSystem
from .workout_structure import structure_for_type, structure_to_json, total_seconds

# Shared thresholds — insights flags, the load chart and the coach all read these.
# The fatigue/fitness ratio (ATL/CTL, the "ACWR") is shown as information only, never a guardrail:
# its injury evidence does not survive re-analysis (Impellizzeri et al. 2020: the same "effects"
# appear when acute load is divided by a fixed or random chronic load).
ACWR_LOW = 0.8
ACWR_HIGH = 1.3
ACWR_DANGER = 1.5

# Weekly ramp is measured against `reference`: the mean of the last 4 normal (not off) weeks. That
# comparison is cumulative, so a steady build of g%/week reads as roughly 2.5 x g against it
# (10%/week -> +26%, 12%/week -> +32%). RAMP_ELEVATED ~ an 8%/week sustained build and RAMP_HIGH
# ~ 11%/week, in line with Friel's 5-8 CTL points/week; the earlier 15% allowed only ~6%/week. No
# trial supports a fixed weekly cap (Buist 2008 RCT; Nielsen 2014 and Frandsen 2025 found weekly
# change not significant), so the flags are advisory.
RAMP_ELEVATED = 20.0
RAMP_HIGH = 30.0
RAMP_MIN_DELTA_H = 1.0  # a week is never flagged unless it is also this many hours above reference

LOAD_UNIT = cardio.LOAD_UNIT  # load, weekly volume and planned values: hours of moving time
MIN_HISTORY_DAYS = 28  # load fields are None until the athlete has this much history
DEFAULT_HORIZON_DAYS = 28

REFERENCE_WEEKS = 4  # reference = mean of this many normal weeks ...
REFERENCE_LOOKBACK_WEEKS = 8  # ... found within this many weeks before the week
REFERENCE_MIN_WEEKS = 3  # fewer normal weeks than this: no reference, no ramp
# An "off" week (travel, illness, a race-recovery week) is set aside from the reference so it
# cannot make the climb back to normal look like a ramp. Off = below OFF_WEEK_FRACTION of the
# median of the 8 weeks before it, or below TRAVEL_OFF_FRACTION when it holds a travel entry. A
# long layoff drags that median down, so its low weeks soon stop being "off" and become the
# baseline: after a real layoff the athlete rebuilds from where they are.
RAMP_MEDIAN_WEEKS = 8  # the median window for off weeks and the typical week
RAMP_MEDIAN_MIN_WEEKS = 6  # of those 8, this many must be inside the athlete's history
OFF_WEEK_FRACTION = 0.6
TRAVEL_OFF_FRACTION = 0.8
# More off weeks in a row than this is a layoff, not a short break: those weeks count in the
# reference, so a return to old volume after one reads as the ramp it is.
MAX_SET_ASIDE_WEEKS = 2
# Recovery: 3:1 loading. A loading week is a normal week at least LOADING_RAMP_PCT above
# reference; a down week is an off week or one at most DOWN_RAMP_PCT. The 4th loading week in a
# row with no down week between is flagged. A travel week counts as the down week.
LOADING_RAMP_PCT = 5.0
LOADING_MIN_DELTA_H = 0.25  # ... and at least 15 min more: a 3-minute rise on a tiny week is noise
DOWN_RAMP_PCT = -20.0
LOADING_WEEKS_BEFORE_DOWN = 3
# Capacity: what the athlete has proven they can do, not what they did last week.
PROVEN_LOOKBACK_WEEKS = 12
PROVEN_TOP_WEEKS = 3  # proven week = median of the 3 biggest normal weeks in the last 12
# Running is the one sport with an evidence-based spike signal: a single run more than 10% longer
# than the longest run of the previous 30 days carries ~1.5-2.3x overuse-injury risk (Frandsen et
# al., BJSM 2025). Measured in moving time; RUN_SPIKE_MIN_MIN keeps a 25 -> 30 min jog quiet.
RUN_SPIKE_WINDOW_DAYS = 30
RUN_SPIKE_PCT = 10.0
RUN_SPIKE_MIN_MIN = 10.0

THRESHOLDS = {
    "acwr_low": ACWR_LOW,
    "acwr_high": ACWR_HIGH,
    "acwr_danger": ACWR_DANGER,
    "ramp_elevated": RAMP_ELEVATED,
    "ramp_high": RAMP_HIGH,
    "ramp_min_delta_h": RAMP_MIN_DELTA_H,
}

_ALPHA_ATL = 1 - math.exp(-1 / cardio.ATL_TIME_CONSTANT_DAYS)
_ALPHA_CTL = 1 - math.exp(-1 / cardio.CTL_TIME_CONSTANT_DAYS)


@dataclass
class Violation:
    """A problem with a (proposed) plan. `hard` violations must not be saved."""

    kind: str  # blocked_day | race_day | ramp_high | no_recovery_week | run_spike
    date: str  # ISO date, or the ISO Monday for week-level kinds
    detail: str
    hard: bool = False

    def to_dict(self) -> dict:
        return {"kind": self.kind, "date": self.date, "detail": self.detail, "hard": self.hard}


@dataclass
class TrainingState:
    as_of: str
    unit: str  # LOAD_UNIT: the unit load, planned and weekly volume values are in
    thresholds: dict
    load: dict  # {ctl, atl, ratio} — each None when history is too short
    projection: list = field(default_factory=list)  # [{date, atl, ctl, ratio, planned}]
    # [{week_start, volume, ramp_pct, baseline, set_aside, off, off_reason, is_current, flags}]
    weeks: list = field(default_factory=list)
    typical_week: Optional[dict] = None  # {median, low, high, weeks} of the previous 8 weeks
    # {proven_week: {volume, weeks} | None, longest: {run|ride: {d30, d90}}, recent_off_weeks}
    capacity: dict = field(default_factory=dict)
    run_spikes: list = field(default_factory=list)  # [{date, hours, longest_hours, longest_date}]
    constraints: dict = field(default_factory=dict)  # {races, blocked_days, next_race}
    conflicts: list = field(default_factory=list)  # [Violation.to_dict()]
    unscored_planned: list = field(default_factory=list)  # planned dates with no usable duration
    mode: Optional[str] = None  # whose sessions count: see _load_scope

    def to_dict(self) -> dict:
        return {
            "as_of": self.as_of,
            "mode": self.mode,
            "unit": self.unit,
            "thresholds": self.thresholds,
            "load": self.load,
            "projection": self.projection,
            "weeks": self.weeks,
            "typical_week": self.typical_week,
            "capacity": self.capacity,
            "run_spikes": self.run_spikes,
            "constraints": self.constraints,
            "conflicts": self.conflicts,
            "unscored_planned": self.unscored_planned,
        }


# ── helpers ─────────────────────────────────────────────────────────────────────


def _counts_for_mode(workout_type: Optional[str], mode: Optional[str]) -> bool:
    """Whether a planned workout's volume belongs to this coaching mode's load."""
    group = classify_workout_type(workout_type)
    if group is SportGroup.UNSCORED:
        return False
    if mode == "running":
        return group in (SportGroup.RUN, SportGroup.AMBIGUOUS)
    if mode == "cycling":
        return group in (SportGroup.RIDE, SportGroup.AMBIGUOUS)
    return True


SHAKEOUT_MAX_MIN = 45


def _is_shakeout(p: dict) -> bool:
    """A short easy session that can sit beside a race (warm-up / shakeout)."""
    minutes = p.get("duration_min")
    return (
        (p.get("intensity") or "").lower() == "easy"
        and minutes is not None
        and minutes <= SHAKEOUT_MAX_MIN
    )


def _is_race_type(workout_type: Optional[str]) -> bool:
    return "race" in (workout_type or "").lower()


def _planned_hours(p: dict) -> Optional[float]:
    """Planned moving time in hours: `duration_min`, or a race's goal time. None when unknown."""
    minutes = p.get("duration_min")
    if (minutes is None or minutes <= 0) and p.get("kind") == "race" and p.get("goal_time_s"):
        minutes = p["goal_time_s"] / 60.0
    return minutes / 60.0 if minutes is not None and minutes > 0 else None


def _planned_by_date(
    plan_rows: list[dict], mode: Optional[str]
) -> tuple[dict[date, float], list[str]]:
    """{date: planned hours}, plus dates of load-bearing workouts that have no duration (they
    contribute nothing rather than a guess)."""
    planned: dict[date, float] = defaultdict(float)
    unscored: list[str] = []
    for p in plan_rows:
        try:
            d = date.fromisoformat(p.get("date") or "")
        except ValueError:
            continue
        if p.get("kind") in ("rest", "travel", "other"):
            continue  # not training: neither load nor "unscored"
        if not _counts_for_mode(p.get("workout_type"), mode):
            continue
        hours = _planned_hours(p)
        if hours is None:
            if (p.get("intensity") or "").lower() != "rest":
                unscored.append(d.isoformat())
            continue
        planned[d] += hours
    return dict(planned), sorted(set(unscored))


REFERENCE_BASIS = "recent normal weeks"


def week_series(
    volumes: list[tuple[date, float]],
    travel_weeks: frozenset[date] = frozenset(),
    race_weeks: frozenset[date] = frozenset(),
    unplanned_weeks: frozenset[date] = frozenset(),
) -> list[dict]:
    """Off weeks, reference, ramp and flags for consecutive weeks. Pure and deterministic.

    `volumes` is [(monday, hours)] for consecutive weeks, oldest first, inside the athlete's
    history only (a week before their first activity is "no data", not a zero week, so the caller
    drops it). Returns one dict per week, same order:
    ``{week_start, volume, off, off_reason, ramp_pct, baseline, set_aside, flags}``

    * ``off`` / ``off_reason``: a short break set aside from the reference. "race" (a low week
      holding a race: taper, or a race with no goal time), "travel" or "low" (see
      OFF_WEEK_FRACTION); never without RAMP_MEDIAN_MIN_WEEKS earlier weeks to compare with. More
      than MAX_SET_ASIDE_WEEKS such weeks in a row are a layoff: ``off`` False, ``off_reason``
      "layoff", counted in the reference so the return is measured against where the athlete is.
      ``unplanned_weeks`` (future weeks with nothing planned yet) are off "unplanned": no ramp,
      and they neither extend nor reset a loading run.
    * ``baseline``: mean of the last REFERENCE_WEEKS weeks that are not off, within
      REFERENCE_LOOKBACK_WEEKS before the week; None with fewer than REFERENCE_MIN_WEEKS of them
      or when it is not positive. ``ramp_pct`` is None exactly when ``baseline`` is.
      ``set_aside`` names the off weeks skipped.
    * ``flags``: "ramp_high" / "ramp_elevated" (never on an off week or a week holding a race, and
      only when also RAMP_MIN_DELTA_H above baseline), "no_recovery_week" (see LOADING_*).
    """
    vols = [v for _, v in volumes]
    # Pass 1: off candidates, from volumes alone (the median ignores earlier verdicts).
    reasons: list[Optional[str]] = []
    for i, (wk, vol) in enumerate(volumes):
        earlier = vols[max(0, i - RAMP_MEDIAN_WEEKS) : i]
        reason = None
        if wk in unplanned_weeks:
            reason = "unplanned"
        elif len(earlier) >= RAMP_MEDIAN_MIN_WEEKS:
            median = statistics.median(earlier)
            if vol < OFF_WEEK_FRACTION * median:
                reason = "race" if wk in race_weeks else "travel" if wk in travel_weeks else "low"
            elif wk in travel_weeks and vol < TRAVEL_OFF_FRACTION * median:
                reason = "travel"
        reasons.append(reason)
    # Pass 2: a run of more than MAX_SET_ASIDE_WEEKS off weeks is a layoff, not a short break.
    i = 0
    while i < len(reasons):
        if reasons[i] in (None, "unplanned"):
            i += 1
            continue
        j = i
        while j < len(reasons) and reasons[j] not in (None, "unplanned"):
            j += 1
        if j - i > MAX_SET_ASIDE_WEEKS:
            reasons[i:j] = ["layoff"] * (j - i)
        i = j

    # Pass 3: reference, ramp and flags.
    out: list[dict] = []
    loading_run = 0
    for i, (wk, vol) in enumerate(volumes):
        off_reason = reasons[i]
        off = off_reason not in (None, "layoff")
        normal: list[float] = []
        set_aside: list[str] = []
        for w in reversed(out[max(0, i - REFERENCE_LOOKBACK_WEEKS) : i]):
            if len(normal) == REFERENCE_WEEKS:
                break
            if w["off"]:
                set_aside.append(w["week_start"])
            else:
                normal.append(w["volume"])
        baseline = ramp = None
        if off_reason != "unplanned" and len(normal) >= REFERENCE_MIN_WEEKS and sum(normal) > 0:
            baseline = sum(normal) / len(normal)
            ramp = round(100 * (vol - baseline) / baseline, 1)

        flags: list[str] = []
        if ramp is not None and not off and wk not in race_weeks:
            big = vol - baseline >= RAMP_MIN_DELTA_H
            if big and ramp > RAMP_HIGH:
                flags.append("ramp_high")
            elif big and ramp > RAMP_ELEVATED:
                flags.append("ramp_elevated")
        if off_reason == "unplanned":
            pass
        elif off or (ramp is not None and ramp <= DOWN_RAMP_PCT):
            loading_run = 0
        elif (
            ramp is not None and ramp >= LOADING_RAMP_PCT and vol - baseline >= LOADING_MIN_DELTA_H
        ):
            loading_run += 1
            if loading_run > LOADING_WEEKS_BEFORE_DOWN:
                flags.append("no_recovery_week")
        out.append(
            {
                "week_start": wk.isoformat(),
                "volume": round(vol, 2),
                "off": off,
                "off_reason": off_reason,
                "ramp_pct": ramp,
                "baseline": None if baseline is None else round(baseline, 2),
                "set_aside": sorted(set_aside),
                "flags": flags,
            }
        )
    return out


def _longest(sessions: list[tuple[date, float]], start: date, end: date) -> Optional[dict]:
    """Longest session (hours) dated in [start, end], earliest on a tie; None when there is none."""
    best = None
    for d, h in sorted(sessions):
        if start <= d <= end and h > 0 and (best is None or h > best[1]):
            best = (d, h)
    return None if best is None else {"hours": round(best[1], 2), "date": best[0].isoformat()}


def _run_spikes(
    actual_runs: list[tuple[date, float]], planned_runs: list[tuple[date, float]]
) -> list[dict]:
    """Planned runs longer than RUN_SPIKE_PCT over the longest run of the previous 30 days (actual
    runs plus planned runs before it), by at least RUN_SPIKE_MIN_MIN. No reference, no flag."""
    out = []
    for d, hours in sorted(planned_runs):
        window = [
            s
            for s in actual_runs + planned_runs
            if d - timedelta(days=RUN_SPIKE_WINDOW_DAYS) <= s[0] < d
        ]
        ref = _longest(window, d - timedelta(days=RUN_SPIKE_WINDOW_DAYS), d)
        if ref is None:
            continue
        if (
            hours > ref["hours"] * (1 + RUN_SPIKE_PCT / 100)
            and (hours - ref["hours"]) * 60 > RUN_SPIKE_MIN_MIN
        ):
            out.append(
                {
                    "date": d.isoformat(),
                    "hours": round(hours, 2),
                    "longest_hours": ref["hours"],
                    "longest_date": ref["date"],
                }
            )
    return out


# ── builder ─────────────────────────────────────────────────────────────────────


def build_training_state(
    rows: list[dict],
    plan_rows: list[dict],
    prefs: dict,
    mode: Optional[str],
    units: UnitSystem,
    today: date,
    horizon_days: int = DEFAULT_HORIZON_DAYS,
) -> TrainingState:
    """Activity rows + plan rows + calendar prefs -> TrainingState. Same inputs, same output.

    `units` is accepted so every caller keeps one call shape; load is moving time, so it does not
    change any number here (display units only matter where a prompt prints distances).
    """
    UnitSystem.parse(units)
    acts = to_cardio_analytics(rows)
    planned, unscored = _planned_by_date(plan_rows, mode)

    prefs = prefs or {}
    races = sorted(
        (r for r in prefs.get("races", []) if (r.get("date") or "") >= today.isoformat()),
        key=lambda r: r["date"],
    )
    blocked = sorted(d for d in prefs.get("blocked_days", []) if d >= today.isoformat())
    next_race = None
    if races:
        r = races[0]
        next_race = {
            "name": r.get("name") or "Race",
            "date": r["date"],
            "days_out": (date.fromisoformat(r["date"]) - today).days,
        }
    constraints = {"races": races, "blocked_days": blocked, "next_race": next_race}

    daily_actual: dict[date, float] = defaultdict(float)
    for a in acts:
        daily_actual[a.date] += (a.moving_time_s or 0.0) / 3600.0

    load = {"ctl": None, "atl": None, "ratio": None}
    projection: list[dict] = []
    has_history = bool(daily_actual) and (today - min(daily_actual)).days >= MIN_HISTORY_DAYS
    if has_history:
        atl = ctl = 0.0
        cur = min(daily_actual)
        while cur <= today:
            if cur < today:
                x = daily_actual.get(cur, 0.0)
                atl += _ALPHA_ATL * (x - atl)
                ctl += _ALPHA_CTL * (x - ctl)
            cur += timedelta(days=1)
        # `atl`/`ctl` now hold the state through yesterday. Today uses whichever is larger of
        # what was done and what is planned, so an unlogged workout still counts.
        day = today
        for i in range(horizon_days + 1):
            actual = daily_actual.get(day, 0.0)
            plan = planned.get(day, 0.0)
            x = max(actual, plan) if day == today else plan
            atl += _ALPHA_ATL * (x - atl)
            ctl += _ALPHA_CTL * (x - ctl)
            ratio = round(atl / ctl, 3) if ctl > 1e-3 else None
            if day == today:
                # Current load = what is actually logged, matching the Analytics chart.
                cur_actual = cardio.compute_atl_ctl(acts, LOAD_UNIT, today).data[-1]
                load = {"ctl": cur_actual.ctl, "atl": cur_actual.atl, "ratio": cur_actual.ratio}
            else:
                projection.append(
                    {
                        "date": day.isoformat(),
                        "atl": round(atl, 3),
                        "ctl": round(ctl, 3),
                        "ratio": ratio,
                        "planned": round(x, 2),
                    }
                )
            day += timedelta(days=1)

    # Weekly volume: past weeks are actual, the current week is actual-to-date plus the rest of
    # the plan, future weeks are planned only.
    cm = monday_of(today)
    horizon_end = today + timedelta(days=horizon_days)
    # Look back far enough that every week of the proven-capacity window has its own off-week
    # median and reference, and a loading run that began in history is seen; only weeks from the
    # current one are returned.
    first_week = cm - timedelta(weeks=PROVEN_LOOKBACK_WEEKS + RAMP_MEDIAN_WEEKS)
    week_starts: list[date] = []
    w = first_week
    while w <= horizon_end:
        week_starts.append(w)
        w += timedelta(weeks=1)

    def volume(week: date) -> float:
        total = 0.0
        for i in range(7):
            d = week + timedelta(days=i)
            if d < today:
                total += daily_actual.get(d, 0.0)
            elif d == today:
                total += max(daily_actual.get(d, 0.0), planned.get(d, 0.0))
            else:
                total += planned.get(d, 0.0)
        return total

    # Weeks before the athlete's first activity are "no data", not "a zero week": counting them
    # would pull every baseline down and inflate every ramp, so the series starts at history.
    history_start = monday_of(min(daily_actual)) if daily_actual else None
    start = cm if history_start is None else min(max(first_week, history_start), cm)
    series_starts = [wk for wk in week_starts if wk >= start]

    def weeks_of(kinds: tuple[str, ...], race_types: bool = False) -> frozenset[date]:
        out = set()
        for p in plan_rows:
            if p.get("kind") in kinds or (race_types and _is_race_type(p.get("workout_type"))):
                try:
                    out.add(monday_of(date.fromisoformat(p.get("date") or "")))
                except ValueError:
                    continue
        return frozenset(out)

    series_vols = [(wk, volume(wk)) for wk in series_starts]
    series = week_series(
        series_vols,
        travel_weeks=weeks_of(("travel",)),
        race_weeks=weeks_of(("race",), race_types=True),
        # A future week with nothing planned yet is not a zero week: it has no ramp to report.
        unplanned_weeks=frozenset(wk for wk, v in series_vols if wk > cm and v == 0),
    )
    weeks = [
        {**w, "is_current": w["week_start"] == cm.isoformat()}
        for w in series
        if w["week_start"] >= cm.isoformat()
    ]
    completed = [w for w in series if w["week_start"] < cm.isoformat()]

    # What the athlete's weeks usually look like: the 8 completed weeks before this one.
    typical = [w["volume"] for w in completed[-RAMP_MEDIAN_WEEKS:]]
    typical_week = (
        {
            "median": round(statistics.median(typical), 2),
            "low": round(min(typical), 2),
            "high": round(max(typical), 2),
            "weeks": len(typical),
        }
        if len(typical) >= RAMP_MEDIAN_MIN_WEEKS
        else None
    )

    # Capacity: the athlete's proven level and longest sessions, so a plan can start from what
    # they have shown they can do rather than from a dip.
    proven_window = completed[-PROVEN_LOOKBACK_WEEKS:]
    top = sorted((w for w in proven_window if not w["off"]), key=lambda w: -w["volume"])
    top = top[:PROVEN_TOP_WEEKS]
    proven_week = (
        {
            "volume": round(statistics.median(w["volume"] for w in top), 2),
            "weeks": [{"week_start": w["week_start"], "volume": w["volume"]} for w in top],
        }
        if len(proven_window) >= RAMP_MEDIAN_MIN_WEEKS and len(top) == PROVEN_TOP_WEEKS
        else None
    )
    sessions: dict[str, list[tuple[date, float]]] = {"run": [], "ride": []}
    for a in acts:
        group = (
            "run" if a.sport_type in RUN_TYPES else "ride" if a.sport_type in CYCLE_TYPES else None
        )
        if group and a.moving_time_s:
            sessions[group].append((a.date, a.moving_time_s / 3600.0))
    longest = {
        g: {
            f"d{n}": _longest(s, today - timedelta(days=n), today)
            for n in (RUN_SPIKE_WINDOW_DAYS, 90)
        }
        for g, s in sessions.items()
        if s
    }
    capacity = {
        "proven_week": proven_week,
        "longest": longest,
        # Short breaks set aside from the ramp, and layoff weeks (counted in it), last 8 weeks.
        "recent_off_weeks": [
            {"week_start": w["week_start"], "volume": w["volume"], "reason": w["off_reason"]}
            for w in completed[-RAMP_MEDIAN_WEEKS:]
            if w["off_reason"] is not None
        ],
    }

    # Single-run spikes (running only: rows are mode-filtered, and cycling mode carries no runs).
    run_spikes: list[dict] = []
    if mode != "cycling":
        planned_runs = []
        for p in plan_rows:
            if (
                p.get("kind", "workout") == "workout"
                and classify_workout_type(p.get("workout_type")) is SportGroup.RUN
                and not _is_race_type(p.get("workout_type"))
                and (p.get("date") or "") >= today.isoformat()
            ):
                hours = _planned_hours(normalized_plan_row(p))
                try:
                    d = date.fromisoformat(p["date"])
                except ValueError:
                    continue
                if hours is not None:
                    planned_runs.append((d, hours))
        run_spikes = _run_spikes(sessions["run"], planned_runs)

    state = TrainingState(
        as_of=today.isoformat(),
        unit=LOAD_UNIT,
        thresholds=dict(THRESHOLDS),
        load=load,
        projection=projection,
        weeks=weeks,
        typical_week=typical_week,
        capacity=capacity,
        run_spikes=run_spikes,
        constraints=constraints,
        unscored_planned=[d for d in unscored if d >= today.isoformat()],
        mode=mode,
    )
    state.conflicts = [v.to_dict() for v in _find_conflicts(state, plan_rows)]
    return state


def _find_conflicts(state: TrainingState, plan_rows: list[dict]) -> list[Violation]:
    out: list[Violation] = []
    c = state.constraints
    blocked = set(c["blocked_days"])
    race_dates = {r["date"]: r.get("name") or "Race" for r in c["races"]}
    today = state.as_of
    for p in sorted(plan_rows, key=lambda p: p.get("date") or ""):
        d = p.get("date") or ""
        wtype = p.get("workout_type")
        if (
            d < today
            or p.get("kind") in ("rest", "travel", "other")
            or (wtype or "") == "Rest"
            or (p.get("intensity") or "") == "rest"
        ):
            continue
        if d in blocked:
            out.append(
                Violation("blocked_day", d, f"{wtype} is planned on a blocked-out day.", True)
            )
        if d in race_dates and not (p.get("kind") == "race" or _is_race_type(wtype)):
            # A short easy shakeout next to the race is fine; anything bigger is not.
            out.append(
                Violation(
                    "race_day",
                    d,
                    f"{wtype} is planned on race day ({race_dates[d]}).",
                    not _is_shakeout(p),
                )
            )
    for wk in state.weeks:
        if "ramp_high" in wk["flags"]:
            out.append(
                Violation(
                    "ramp_high",
                    wk["week_start"],
                    f"Week of {wk['week_start']} is {wk['ramp_pct']:+.0f}% vs "
                    f"{REFERENCE_BASIS} ({wk['baseline']:.1f} {LOAD_UNIT}), above the "
                    f"+{RAMP_HIGH:.0f}% screening line (advisory).",
                )
            )
        if "no_recovery_week" in wk["flags"]:
            out.append(
                Violation(
                    "no_recovery_week",
                    wk["week_start"],
                    f"Week of {wk['week_start']} is another loading week after "
                    f"{LOADING_WEEKS_BEFORE_DOWN} with no down or off week between; consider a "
                    "down week (advisory).",
                )
            )
    for s in state.run_spikes:
        out.append(
            Violation(
                "run_spike",
                s["date"],
                f"Run on {s['date']} is {s['hours'] * 60:.0f} min, more than "
                f"{RUN_SPIKE_PCT:.0f}% over the longest run of the previous "
                f"{RUN_SPIKE_WINDOW_DAYS} days ({s['longest_hours'] * 60:.0f} min on "
                f"{s['longest_date']}); single-run spikes are the best-evidenced running injury "
                "risk (advisory).",
            )
        )
    return out


# ── guardrails for proposed plan edits ──────────────────────────────────────────


def _normalize_planned_structure(row: dict) -> None:
    """Mirror calendar storage: retained or supplied structure overrides duration.

    An explicit null removes structure; an omitted field retains the stored JSON.
    Invalid structures and non-cycling types leave the supplied duration unchanged.
    """
    if row.get("kind", "workout") != "workout":
        return
    structure = structure_for_type(
        row.get("workout_type"), row.get("structure", row.get("structure_json"))
    )
    if structure:
        row["duration_min"] = round(total_seconds(structure) / 60)
    row.pop("structure", None)
    row["structure_json"] = structure_to_json(structure)


CHANGE_KEYS = frozenset({"create", "update", "delete"})

# The fields of an update that move load or trigger a guardrail (a title or note cannot).
_UPDATE_FIELDS = (
    "date",
    "workout_type",
    "distance_km",
    "duration_min",
    "structure",
    "goal_time_s",
    "intensity",
)


def changes_from_ops(ops: list[dict], plan_rows: list[dict]) -> dict:
    """Calendar ops (``{"op": "create" | "update" | "delete", ...}``, the shape
    ``db.calendar.apply_changes`` takes) -> the change set ``apply_changes`` above reads.

    Mirrors ``backends.base._plan_ops``, which builds the same thing from the coach's tool args;
    a test pins the two together so a preview and the commit see the same plan. An update of an
    id that is not in ``plan_rows`` is kept: ``apply_changes`` ignores it, as the calendar would
    refuse it.
    """
    out: dict = {"create": [], "update": [], "delete": []}
    for op in ops:
        kind = op.get("op")
        if kind == "delete" and op.get("id") is not None:
            out["delete"].append(int(op["id"]))
        elif kind == "update" and op.get("id") is not None:
            out["update"].append(
                {"id": int(op["id"]), **{k: op[k] for k in _UPDATE_FIELDS if k in op}}
            )
        elif kind == "create":
            entry_kind = op.get("kind") or "workout"
            out["create"].append(
                {
                    "date": op.get("date"),
                    "kind": entry_kind,
                    "workout_type": display_type(
                        entry_kind, op.get("workout_type"), op.get("sport")
                    ),
                    "distance_km": op.get("distance_km"),
                    "duration_min": op.get("duration_min"),
                    "structure": op.get("structure"),
                    "goal_time_s": op.get("goal_time_s"),
                    "intensity": op.get("intensity"),
                }
            )
    return out


def normalized_plan_row(p: dict) -> dict:
    """A copy of a plan row as the calendar would store it: a valid structure decides the duration
    (see `_normalize_planned_structure`), so a structured ride with no `duration_min` still has one.
    """
    row = dict(p)
    _normalize_planned_structure(row)
    return row


def describe_planned_load(
    p: dict, mode: Optional[str], today: date, horizon_days: int = DEFAULT_HORIZON_DAYS
) -> dict:
    """What one planned entry contributes to load, and why not when it contributes nothing.

    ``{"hours": float | None, "reason": None | "past" | "beyond_horizon" | "not_in_load" |
    "no_duration"}``. ``hours`` is the entry's own planned time (None when unknown); ``reason`` is
    set when the load model ignores it: a date before today (past days use what was logged), a
    date past the projection horizon, a type that is not load in this mode (Yoga, rest, travel,
    another sport's workout), or no usable duration. Today counts the larger of what is logged and
    what is planned, so an entry for today can still move nothing once that much is logged.
    """
    p = normalized_plan_row(p)
    hours = _planned_hours(p)
    try:
        d = date.fromisoformat(p.get("date") or "")
    except ValueError:
        return {"hours": hours, "reason": "past"}
    if d < today:
        reason = "past"
    elif d > today + timedelta(days=horizon_days):
        reason = "beyond_horizon"
    elif p.get("kind") in ("rest", "travel", "other") or not _counts_for_mode(
        p.get("workout_type"), mode
    ):
        reason = "not_in_load"
    elif hours is None:
        reason = "no_duration"
    else:
        reason = None
    return {"hours": hours, "reason": reason}


def apply_changes(plan_rows: list[dict], changes: dict) -> list[dict]:
    """Return plan_rows with an entry change set applied. Does not mutate the input.

    ``changes``: ``{"create": [{date, workout_type, distance_km, intensity, kind?}],
    "update": [{id, ...fields}], "delete": [id]}`` — the same shape the calendar applies, so the
    guardrail preview and the commit see the same plan. Any other key raises: a caller that
    passes a shape this function does not read would otherwise be checked against an unchanged
    plan without noticing.
    """
    unknown = set(changes) - CHANGE_KEYS
    if unknown:
        raise ValueError(
            f"Unknown change keys {sorted(unknown)}; expected create / update / delete"
        )
    by_id: dict = {p["id"]: dict(p) for p in plan_rows if p.get("id") is not None}
    anonymous = [dict(p) for p in plan_rows if p.get("id") is None]
    for entry_id in changes.get("delete") or []:
        by_id.pop(entry_id, None)
    for u in changes.get("update") or []:
        if u.get("id") in by_id:
            merged = by_id[u["id"]]
            merged.update({k: v for k, v in u.items() if k != "id"})
            _normalize_planned_structure(merged)
    created = []
    for w in changes.get("create") or []:
        if w.get("date"):
            created.append(
                {
                    "date": w["date"],
                    "kind": w.get("kind", "workout"),
                    "workout_type": w.get("workout_type", "Workout"),
                    "distance_km": w.get("distance_km"),
                    "duration_min": w.get("duration_min"),
                    "structure": w.get("structure", w.get("structure_json")),
                    "goal_time_s": w.get("goal_time_s"),
                    "intensity": w.get("intensity"),
                }
            )
    for row in created:
        _normalize_planned_structure(row)
    return list(by_id.values()) + anonymous + created


def check_plan_changes(
    rows: list[dict],
    plan_rows: list[dict],
    prefs: dict,
    mode: Optional[str],
    units: UnitSystem,
    today: date,
    changes: dict,
) -> list[Violation]:
    """Violations a proposed entry change set (see apply_changes) would introduce.

    Hard: scheduling a non-race workout on a blocked-out day or race day. Soft (advisory): weekly
    ramp, a 4th loading week or a run spike that the change *creates* (the same problem already
    present in the plan before the change is not reported again).
    """
    before = build_training_state(rows, plan_rows, prefs, mode, units, today)
    after_rows = apply_changes(plan_rows, changes)
    after = build_training_state(rows, after_rows, prefs, mode, units, today)
    return violations_introduced(before, after, plan_rows, changes)


def violations_introduced(
    before: TrainingState, after: TrainingState, plan_rows: list[dict], changes: dict
) -> list[Violation]:
    """What `check_plan_changes` reports, from states already built (the what-if digest reuses
    them instead of building each twice)."""
    existing = {(v["kind"], v["date"]) for v in before.conflicts}
    by_id = {p.get("id"): p for p in plan_rows}
    touched = {w["date"] for w in changes.get("create") or [] if w.get("date")}
    for u in changes.get("update") or []:
        touched.add(u.get("date") or (by_id.get(u.get("id")) or {}).get("date"))
    touched.discard(None)
    out: list[Violation] = []
    for v in after.conflicts:
        v_obj = Violation(v["kind"], v["date"], v["detail"], v["hard"])
        if v_obj.hard:
            if v_obj.date in touched:
                out.append(v_obj)
        elif (v_obj.kind, v_obj.date) not in existing:
            out.append(v_obj)
    return out


# ── prompt rendering ────────────────────────────────────────────────────────────


def render_for_prompt(state: TrainingState, units: UnitSystem = DEFAULT_UNIT_SYSTEM) -> str:
    """The "Training State" section shared by the chat coach and plan generation."""
    u = LOAD_UNIT
    ld = state.load
    lines = []
    if ld["ctl"] is None:
        lines.append("Current load: not enough history (under 28 days) to compute.")
    else:
        ratio = "n/a" if ld["ratio"] is None else f"{ld['ratio']:.2f}"
        lines.append(
            f"Current load: fitness (CTL) {ld['ctl']:.2f} {u}/day, fatigue (ATL) "
            f"{ld['atl']:.2f} {u}/day, fatigue/fitness ratio {ratio}."
        )
        peak = max(
            (p for p in state.projection[:UPCOMING_DAYS_FOR_PROMPT] if p["ratio"] is not None),
            key=lambda p: p["ratio"],
            default=None,
        )
        if peak:
            lines.append(
                f"As currently planned, the ratio peaks at {peak['ratio']:.2f} on {peak['date']}."
            )
    tw = state.typical_week
    if tw:
        lines.append(
            f"Typical week (the previous {tw['weeks']} completed weeks): median {tw['median']:.1f} "
            f"{u}, range {tw['low']:.1f}-{tw['high']:.1f} {u}."
        )
    lines += _render_capacity(state.capacity)
    if state.weeks:
        lines.append(
            f"Weekly volume in {u} (actual to date + planned; ramp is vs the mean of the last "
            f"{REFERENCE_WEEKS} normal weeks, off weeks set aside):"
        )
        for w in state.weeks:
            if w["off_reason"] == "unplanned":
                lines.append(f"  - week of {w['week_start']}: nothing planned yet")
                continue
            ramp = ""
            if w["ramp_pct"] is not None:
                ramp = f", {w['ramp_pct']:+.0f}% vs {REFERENCE_BASIS} ({w['baseline']:.1f} {u})"
            off = f" [{'off: ' if w['off'] else ''}{w['off_reason']}]" if w["off_reason"] else ""
            flags = f" [{', '.join(w['flags'])}]" if w["flags"] else ""
            lines.append(f"  - week of {w['week_start']}: {w['volume']:.1f} {u}{ramp}{off}{flags}")
    if state.unscored_planned:
        lines.append(
            "Planned entries with no duration are not counted in load (a race counts only when it "
            "has a goal time, so a race week reads low): " + ", ".join(state.unscored_planned)
        )
    if state.conflicts:
        lines.append("Open notes on the current plan:")
        lines += [f"  - {c['detail']}" for c in state.conflicts]
    lines.append(
        "These numbers are screening notes, not injury predictions or limits; plan with the "
        "Planning Principles. Off weeks (travel, illness, race recovery, a race-week taper) are "
        "set aside from the ramp, and an off week already counts as a down week. Moving time is a volume proxy, "
        "not intensity-weighted stress; cycling carries far less impact load than running. The "
        f"fatigue/fitness ratio is context only (above {ACWR_DANGER} after a big week is normal). "
        "Never schedule on blocked-out days or race days."
    )
    return (
        f"## Training State (load = logged and planned moving time of {_load_scope(state.mode)})\n"
        + "\n".join(lines)
    )


UPCOMING_DAYS_FOR_PROMPT = 14


def _load_scope(mode: Optional[str]) -> str:
    """Which sessions this mode's load counts, so a running-only ramp is never read as all sports."""
    if mode == "running":
        return "runs only, plus planned cross-training and strength; rides are not counted"
    if mode == "cycling":
        return "rides only, plus planned cross-training and strength; runs are not counted"
    return "all sports"


def _fmt_hours(hours: float) -> str:
    return f"{hours:.1f} h" if hours >= 1.5 else f"{hours * 60:.0f} min"


def _render_capacity(capacity: dict) -> list[str]:
    """Proven level, longest sessions and recent off weeks: what a coach starts a block from."""
    u = LOAD_UNIT
    lines = []
    pw = (capacity or {}).get("proven_week")
    if pw:
        weeks = ", ".join(f"{w['week_start']} {w['volume']:.1f}" for w in pw["weeks"])
        lines.append(
            f"Proven weekly level: {pw['volume']:.1f} {u} (median of the {PROVEN_TOP_WEEKS} biggest "
            f"normal weeks in the last {PROVEN_LOOKBACK_WEEKS}: {weeks})."
        )
    names = {"run": "run", "ride": "ride"}
    for group, spans in ((capacity or {}).get("longest") or {}).items():
        parts = [
            (
                f"last {k[1:]} days {_fmt_hours(v['hours'])} ({v['date']})"
                if v
                else f"last {k[1:]} days none"
            )
            for k, v in spans.items()
        ]
        lines.append(f"Longest {names.get(group, group)}: " + "; ".join(parts) + ".")
    recent = (capacity or {}).get("recent_off_weeks") or []
    off = [w for w in recent if w["reason"] != "layoff"]
    layoff = [w for w in recent if w["reason"] == "layoff"]
    if off:
        lines.append(
            "Off weeks set aside from the ramp: "
            + ", ".join(f"{w['week_start']} ({w['volume']:.1f} {u}, {w['reason']})" for w in off)
            + "."
        )
    if layoff:
        lines.append(
            f"Layoff ({len(layoff)} low weeks in a row, counted in the ramp; rebuild from the "
            "current level, not the proven one): "
            + ", ".join(f"{w['week_start']} ({w['volume']:.1f} {u})" for w in layoff)
            + "."
        )
    return lines
