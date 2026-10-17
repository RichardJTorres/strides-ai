"""One deterministic view of the athlete's training: current load, planned load and constraints.

Insights, the coach prompt, plan generation, the `update_training_plan` tool and the Calendar /
Analytics UIs all read this, so they cannot disagree about load thresholds, ramp rate or which
days are off limits.

Pure: no DB access, every function takes `today` explicitly (same rule as analytics/cardio.py).
Load is distance-based in the athlete's display unit, matching `cardio.compute_atl_ctl`.
"""

import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

from .analytics import cardio
from .analytics.adapters import to_cardio_analytics
from .analytics.aggregation import monday_of
from .compliance import SportGroup, classify_workout_type
from .units import DEFAULT_UNIT_SYSTEM, Quantity, UnitSystem, convert, unit_label

# Shared thresholds — insights flags, the load chart and the coach all read these.
ACWR_LOW = 0.8
ACWR_HIGH = 1.3
ACWR_DANGER = 1.5
RAMP_ELEVATED = 10.0  # % vs the prior-4-week average
RAMP_HIGH = 15.0

MIN_HISTORY_DAYS = 28  # load fields are None until the athlete has this much history
DEFAULT_HORIZON_DAYS = 28
RAMP_BASELINE_WEEKS = 4
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
    unit: str  # "km" | "miles": the unit load / planned_km values are in
    thresholds: dict
    load: dict  # {ctl, atl, ratio} — each None when history is too short
    projection: list = field(default_factory=list)  # [{date, atl, ctl, ratio, planned}]
    weeks: list = field(
        default_factory=list
    )  # [{week_start, volume, planned_only, ramp_pct, flags}]
    constraints: dict = field(default_factory=dict)  # {races, blocked_days, next_race}
    conflicts: list = field(default_factory=list)  # [Violation.to_dict()]
    unscored_planned: list = field(default_factory=list)  # planned dates with no usable distance

    def to_dict(self) -> dict:
        return {
            "as_of": self.as_of,
            "unit": self.unit,
            "thresholds": self.thresholds,
            "load": self.load,
            "projection": self.projection,
            "weeks": self.weeks,
            "constraints": self.constraints,
            "conflicts": self.conflicts,
            "unscored_planned": self.unscored_planned,
        }


# ── helpers ─────────────────────────────────────────────────────────────────────


def _unit_name(units: UnitSystem) -> str:
    return "miles" if units is UnitSystem.IMPERIAL else "km"


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


def _is_race_type(workout_type: Optional[str]) -> bool:
    return "race" in (workout_type or "").lower()


def _planned_by_date(
    plan_rows: list[dict], mode: Optional[str], units: UnitSystem
) -> tuple[dict[date, float], list[str]]:
    """{date: planned distance in the display unit}, plus dates of volume-bearing workouts that
    have no distance (they contribute nothing rather than a guess)."""
    planned: dict[date, float] = defaultdict(float)
    unscored: list[str] = []
    for p in plan_rows:
        try:
            d = date.fromisoformat(p.get("date") or "")
        except ValueError:
            continue
        if not _counts_for_mode(p.get("workout_type"), mode):
            continue
        km = p.get("distance_km")
        if km is None or km <= 0:
            if (p.get("intensity") or "").lower() != "rest":
                unscored.append(d.isoformat())
            continue
        planned[d] += convert(km * 1000.0, Quantity.DISTANCE, units)
    return dict(planned), sorted(set(unscored))


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
    """Activity rows + plan rows + calendar prefs -> TrainingState. Same inputs, same output."""
    units = UnitSystem.parse(units)
    unit = _unit_name(units)
    acts = to_cardio_analytics(rows)
    planned, unscored = _planned_by_date(plan_rows, mode, units)

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
        daily_actual[a.date] += convert(a.distance_m or 0.0, Quantity.DISTANCE, units)

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
                cur_actual = cardio.compute_atl_ctl(acts, unit, today).data[-1]
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
    first_week = cm - timedelta(weeks=RAMP_BASELINE_WEEKS)
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
    chrono: list[tuple[date, float, Optional[float]]] = []
    for i, wk in enumerate(week_starts):
        if i < RAMP_BASELINE_WEEKS:
            continue
        prior = [vols[week_starts[j]] for j in range(i - RAMP_BASELINE_WEEKS, i)]
        base = sum(prior) / len(prior)
        ramp = round(100 * (vols[wk] - base) / base, 1) if base > 0 else None
        chrono.append((wk, vols[wk], ramp))
    flags = _week_flags(chrono)
    weeks = [
        {
            "week_start": wk.isoformat(),
            "volume": round(vol, 2),
            "ramp_pct": ramp,
            "is_current": wk == cm,
            "flags": flags[wk],
        }
        for wk, vol, ramp in chrono
        if wk >= cm
    ]

    state = TrainingState(
        as_of=today.isoformat(),
        unit=unit,
        thresholds=dict(THRESHOLDS),
        load=load,
        projection=projection,
        weeks=weeks,
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
        if d < today or (wtype or "") == "Rest" or (p.get("intensity") or "") == "rest":
            continue
        if d in blocked:
            out.append(
                Violation("blocked_day", d, f"{wtype} is planned on a blocked-out day.", True)
            )
        if d in race_dates and not _is_race_type(wtype):
            out.append(
                Violation("race_day", d, f"{wtype} is planned on race day ({race_dates[d]}).", True)
            )
    for wk in state.weeks:
        if "ramp_high" in wk["flags"]:
            out.append(
                Violation(
                    "ramp_high",
                    wk["week_start"],
                    f"Week of {wk['week_start']} is {wk['ramp_pct']:+.0f}% vs the prior 4-week "
                    f"average (limit +{RAMP_HIGH:.0f}%).",
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
    """Return plan_rows with `changes` ({"set": [{date, workout_type, distance_km, ...}],
    "delete": [date]}) applied. Does not mutate the input."""
    by_date = {p["date"]: dict(p) for p in plan_rows if p.get("date")}
    for d in changes.get("delete") or []:
        by_date.pop(d, None)
    for w in changes.get("set") or []:
        if w.get("date"):
            by_date[w["date"]] = {
                "date": w["date"],
                "workout_type": w.get("workout_type", "Workout"),
                "distance_km": w.get("distance_km"),
                "intensity": w.get("intensity"),
            }
    return list(by_date.values())


def check_plan_changes(
    rows: list[dict],
    plan_rows: list[dict],
    prefs: dict,
    mode: Optional[str],
    units: UnitSystem,
    today: date,
    changes: dict,
) -> list[Violation]:
    """Violations a proposed change set would introduce.

    Hard: scheduling a non-race workout on a blocked-out day or race day. Soft: weekly ramp,
    projected ratio breach or missing recovery week that the change *creates* (the same problem
    already present in the plan before the change is not reported again).
    """
    before = build_training_state(rows, plan_rows, prefs, mode, units, today)
    after_rows = apply_changes(plan_rows, changes)
    after = build_training_state(rows, after_rows, prefs, mode, units, today)

    existing = {(v["kind"], v["date"]) for v in before.conflicts}
    touched = {w["date"] for w in changes.get("set") or [] if w.get("date")}
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
    u = unit_label(Quantity.DISTANCE, units)
    ld = state.load
    lines = []
    if ld["ctl"] is None:
        lines.append("Current load: not enough history (under 28 days) to compute.")
    else:
        ratio = "n/a" if ld["ratio"] is None else f"{ld['ratio']:.2f}"
        lines.append(
            f"Current load: fitness (CTL) {ld['ctl']:.1f} {u}/day, fatigue (ATL) "
            f"{ld['atl']:.1f} {u}/day, fatigue/fitness ratio {ratio}."
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
    if state.weeks:
        lines.append("Weekly volume (actual to date + planned):")
        for w in state.weeks:
            ramp = "" if w["ramp_pct"] is None else f", {w['ramp_pct']:+.0f}% vs prior 4-wk avg"
            flags = f" [{', '.join(w['flags'])}]" if w["flags"] else ""
            lines.append(f"  - week of {w['week_start']}: {w['volume']:.1f} {u}{ramp}{flags}")
    if state.unscored_planned:
        lines.append(
            "Planned workouts with no distance (not counted in load): "
            + ", ".join(state.unscored_planned)
        )
    if state.conflicts:
        lines.append("Open problems in the current plan:")
        lines += [f"  - {c['detail']}" for c in state.conflicts]
    lines.append(
        f"Guardrails: ratio {ACWR_LOW}-{ACWR_HIGH} is the target band (>{ACWR_HIGH} raises injury "
        f"risk, >{ACWR_DANGER} is danger); keep week-on-week ramp under +{RAMP_ELEVATED:.0f}% "
        f"(never above +{RAMP_HIGH:.0f}%); add a down week after {RECOVERY_RUN_WEEKS} rising "
        "weeks; taper before races; never schedule on blocked-out days or race days."
    )
    return "## Training State (computed from the data, not an estimate)\n" + "\n".join(lines)


UPCOMING_DAYS_FOR_PROMPT = 14
