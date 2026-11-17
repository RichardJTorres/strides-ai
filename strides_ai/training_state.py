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

from .analytics import cardio
from .analytics.adapters import to_cardio_analytics
from .analytics.aggregation import monday_of
from .compliance import SportGroup, classify_workout_type
from .units import DEFAULT_UNIT_SYSTEM, UnitSystem

# Shared thresholds — insights flags, the load chart and the coach all read these.
ACWR_LOW = 0.8
ACWR_HIGH = 1.3
ACWR_DANGER = 1.5
RAMP_ELEVATED = 10.0  # % above the athlete's typical week (see the ramp baselines below)
RAMP_HIGH = 15.0

LOAD_UNIT = cardio.LOAD_UNIT  # load, weekly volume and planned values: hours of moving time
MIN_HISTORY_DAYS = 28  # load fields are None until the athlete has this much history
DEFAULT_HORIZON_DAYS = 28
# A week's ramp is measured against two baselines and reported as the smaller of the two, so a
# week is only flagged when it is high against both the recent mean AND the typical (median)
# week. One or two travel or deload weeks cannot depress the median the way they depress a mean.
RAMP_BASELINE_WEEKS = 4  # mean of the previous 4 weeks
RAMP_MEDIAN_WEEKS = 8  # median of the previous 8 weeks
RAMP_MEDIAN_MIN_WEEKS = 6  # of those 8, this many must be inside the athlete's history
TAPER_WINDOW_DAYS = 21
RECOVERY_RUN_WEEKS = 3  # this many consecutive rising weeks without a down week

THRESHOLDS = {
    "acwr_low": ACWR_LOW,
    "acwr_high": ACWR_HIGH,
    "acwr_danger": ACWR_DANGER,
    "ramp_elevated": RAMP_ELEVATED,
    "ramp_high": RAMP_HIGH,
}

_ALPHA_ATL = 1 - math.exp(-1 / cardio.ATL_TIME_CONSTANT_DAYS)
_ALPHA_CTL = 1 - math.exp(-1 / cardio.CTL_TIME_CONSTANT_DAYS)


@dataclass
class Violation:
    """A problem with a (proposed) plan. `hard` violations must not be saved."""

    kind: str  # blocked_day | race_day | ramp_high | ratio_breach | no_recovery_week
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
    weeks: list = field(
        default_factory=list
    )  # [{week_start, volume, ramp_pct, baseline, baseline_basis, is_current, flags}]
    typical_week: Optional[dict] = None  # {median, low, high, weeks} of the previous 8 weeks
    constraints: dict = field(default_factory=dict)  # {races, blocked_days, next_race}
    conflicts: list = field(default_factory=list)  # [Violation.to_dict()]
    unscored_planned: list = field(default_factory=list)  # planned dates with no usable duration

    def to_dict(self) -> dict:
        return {
            "as_of": self.as_of,
            "unit": self.unit,
            "thresholds": self.thresholds,
            "load": self.load,
            "projection": self.projection,
            "weeks": self.weeks,
            "typical_week": self.typical_week,
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
        if not _counts_for_mode(p.get("workout_type"), mode):
            continue
        hours = _planned_hours(p)
        if hours is None:
            if (p.get("intensity") or "").lower() != "rest":
                unscored.append(d.isoformat())
            continue
        planned[d] += hours
    return dict(planned), sorted(set(unscored))


def ramp_vs_baselines(
    volume: float, prior: list[float]
) -> tuple[Optional[float], Optional[float], Optional[str]]:
    """(ramp %, baseline, basis) for one week's `volume` against the weeks before it.

    `prior` is weekly volumes, oldest first, only for weeks inside the athlete's history (a week
    before their first activity is "no data", not a zero week). Two baselines are tried: the mean
    of the last RAMP_BASELINE_WEEKS (needs all of them) and the median of the last
    RAMP_MEDIAN_WEEKS (needs RAMP_MEDIAN_MIN_WEEKS). The smaller ramp wins, so a week is high only
    when it is high against both. (None, None, None) when neither baseline exists or is positive.
    """
    prior = prior[-RAMP_MEDIAN_WEEKS:]
    recent = prior[-RAMP_BASELINE_WEEKS:]
    mean4 = sum(recent) / len(recent) if len(recent) == RAMP_BASELINE_WEEKS else None
    median8 = statistics.median(prior) if len(prior) >= RAMP_MEDIAN_MIN_WEEKS else None
    candidates: list[tuple[float, float, str]] = []
    for base, basis in ((mean4, "4-week average"), (median8, "8-week median")):
        if base is not None and base > 0:
            candidates.append((round(100 * (volume - base) / base, 1), base, basis))
    return min(candidates, default=(None, None, None))


def _week_flags(volumes: list[tuple[date, float, Optional[float]]]) -> dict[date, list[str]]:
    """Rule flags per week from [(monday, volume, ramp_pct)] in chronological order."""
    flags: dict[date, list[str]] = {}
    for i, (wk, vol, ramp) in enumerate(volumes):
        f: list[str] = []
        if ramp is not None and ramp > RAMP_HIGH:
            f.append("ramp_high")
        elif ramp is not None and ramp > RAMP_ELEVATED:
            f.append("ramp_elevated")
        if i >= RECOVERY_RUN_WEEKS:
            window = [v for _, v, _ in volumes[i - RECOVERY_RUN_WEEKS : i + 1]]
            if all(b > a for a, b in zip(window, window[1:])):
                f.append("no_recovery_week")
        flags[wk] = f
    return flags


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
    # Look back far enough to give the earliest kept week both ramp baselines AND to let a rising
    # streak that began in actual history be detected; only weeks from the current one are returned.
    first_week = cm - timedelta(weeks=RAMP_MEDIAN_WEEKS + RECOVERY_RUN_WEEKS)
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

    vols = {wk: volume(wk) for wk in week_starts}
    # Weeks before the athlete's first activity are "no data", not "a zero week": counting them
    # would pull both baselines down and inflate every ramp.
    history_start = monday_of(min(daily_actual)) if daily_actual else None

    def prior_volumes(i: int, n: int) -> list[float]:
        return [
            vols[week_starts[j]]
            for j in range(i - n, i)
            if history_start is not None and week_starts[j] >= history_start
        ]

    chrono: list[tuple[date, float, Optional[float]]] = []
    bases: dict[date, tuple[Optional[float], Optional[str]]] = {}
    for i, wk in enumerate(week_starts):
        if i < RAMP_MEDIAN_WEEKS:
            continue
        ramp, base, basis = ramp_vs_baselines(vols[wk], prior_volumes(i, RAMP_MEDIAN_WEEKS))
        chrono.append((wk, vols[wk], ramp))
        bases[wk] = (base, basis)
    flags = _week_flags(chrono)
    weeks = [
        {
            "week_start": wk.isoformat(),
            "volume": round(vol, 2),
            "ramp_pct": ramp,
            "baseline": None if bases[wk][0] is None else round(bases[wk][0], 2),
            "baseline_basis": bases[wk][1],
            "is_current": wk == cm,
            "flags": flags[wk],
        }
        for wk, vol, ramp in chrono
        if wk >= cm
    ]

    # What the athlete's weeks usually look like: the 8 completed weeks before this one.
    cm_index = week_starts.index(cm)
    typical = prior_volumes(cm_index, RAMP_MEDIAN_WEEKS)
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

    state = TrainingState(
        as_of=today.isoformat(),
        unit=LOAD_UNIT,
        thresholds=dict(THRESHOLDS),
        load=load,
        projection=projection,
        weeks=weeks,
        typical_week=typical_week,
        constraints=constraints,
        unscored_planned=[d for d in unscored if d >= today.isoformat()],
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
                    f"Week of {wk['week_start']} is {wk['ramp_pct']:+.0f}% vs the "
                    f"{wk['baseline_basis']} ({wk['baseline']:.1f} {LOAD_UNIT}); limit "
                    f"+{RAMP_HIGH:.0f}%.",
                )
            )
        if "no_recovery_week" in wk["flags"]:
            out.append(
                Violation(
                    "no_recovery_week",
                    wk["week_start"],
                    f"Volume has risen {RECOVERY_RUN_WEEKS} weeks in a row up to the week of "
                    f"{wk['week_start']}; consider a down week.",
                )
            )
    breach = next(
        (p for p in state.projection if p["ratio"] is not None and p["ratio"] > ACWR_HIGH), None
    )
    if breach:
        out.append(
            Violation(
                "ratio_breach",
                breach["date"],
                f"Projected fatigue/fitness ratio reaches {breach['ratio']:.2f} on "
                f"{breach['date']} (limit {ACWR_HIGH}).",
            )
        )
    return out


# ── guardrails for proposed plan edits ──────────────────────────────────────────


def apply_changes(plan_rows: list[dict], changes: dict) -> list[dict]:
    """Return plan_rows with an entry change set applied. Does not mutate the input.

    ``changes``: ``{"create": [{date, workout_type, distance_km, intensity, kind?}],
    "update": [{id, ...fields}], "delete": [id]}`` — the same shape the calendar applies, so the
    guardrail preview and the commit see the same plan.
    """
    by_id: dict = {p["id"]: dict(p) for p in plan_rows if p.get("id") is not None}
    anonymous = [dict(p) for p in plan_rows if p.get("id") is None]
    for entry_id in changes.get("delete") or []:
        by_id.pop(entry_id, None)
    for u in changes.get("update") or []:
        if u.get("id") in by_id:
            by_id[u["id"]].update({k: v for k, v in u.items() if k != "id"})
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
                    "goal_time_s": w.get("goal_time_s"),
                    "intensity": w.get("intensity"),
                }
            )
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

    Hard: scheduling a non-race workout on a blocked-out day or race day. Soft: weekly ramp,
    projected ratio breach or missing recovery week that the change *creates* (the same problem
    already present in the plan before the change is not reported again).
    """
    before = build_training_state(rows, plan_rows, prefs, mode, units, today)
    after_rows = apply_changes(plan_rows, changes)
    after = build_training_state(rows, after_rows, prefs, mode, units, today)

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
        elif v_obj.kind == "ratio_breach":
            # The breach date shifts as the plan changes; only report a breach the change creates.
            if not any(k == "ratio_breach" for k, _ in existing):
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
    if state.weeks:
        lines.append(f"Weekly volume in {u} (actual to date + planned):")
        for w in state.weeks:
            ramp = ""
            if w["ramp_pct"] is not None:
                ramp = f", {w['ramp_pct']:+.0f}% vs the {w['baseline_basis']} ({w['baseline']:.1f} {u})"
            flags = f" [{', '.join(w['flags'])}]" if w["flags"] else ""
            lines.append(f"  - week of {w['week_start']}: {w['volume']:.1f} {u}{ramp}{flags}")
    if state.unscored_planned:
        lines.append(
            "Planned entries with no duration are not counted in load (a race counts only when it "
            "has a goal time, so a race week reads low): " + ", ".join(state.unscored_planned)
        )
    if state.conflicts:
        lines.append("Open problems in the current plan:")
        lines += [f"  - {c['detail']}" for c in state.conflicts]
    lines.append(
        "Guardrails are screening heuristics, not injury predictions. Before calling a plan risky, "
        "weigh them against the typical week above, the athlete's own fatigue, sleep, travel and "
        "recent history, and say which of those you used. "
        f"Fatigue/fitness ratio {ACWR_LOW}-{ACWR_HIGH} is the usual target band (above {ACWR_HIGH} "
        f"fatigue is high relative to fitness; above {ACWR_DANGER} it is very high). Week-on-week "
        f"volume more than +{RAMP_ELEVATED:.0f}% above the typical week deserves a look, and more "
        f"than +{RAMP_HIGH:.0f}% needs a reason. Add a down week after {RECOVERY_RUN_WEEKS} rising "
        "weeks and taper before races. Never schedule on blocked-out days or race days."
    )
    return "## Training State (load = moving time, logged and planned)\n" + "\n".join(lines)


UPCOMING_DAYS_FOR_PROMPT = 14
