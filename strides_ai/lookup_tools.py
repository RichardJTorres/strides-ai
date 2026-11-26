"""Read-only lookup tools for the chat coach: find activities, weekly totals, calendar entries.

The coach's prompt carries only the 30 most recent activities and aggregates of older ones, so it
used to guess ("your longest climb is 3,862 ft") or give up ("I can't search your runs"). These
tools let it check. They are specified once here (`READ_TOOLS`) and rendered into each provider's
format by the backend modules; `run_read_tool` executes one and returns the text for the model.

Pure apart from the loaders the caller passes in: `today` and `units` are parameters, results are
deterministic and bounded (a few thousand tokens at most), and every argument problem comes back
as an `Error: ...` string the model can act on, never as an exception.
"""

import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Callable

from .activity_types import CYCLE_TYPES, LIFT_TYPES, RUN_TYPES
from .analytics.aggregation import monday_of
from .coach import PLAN_TABLE_HEADER, build_training_log, plan_row_text
from .dates import fmt_day, parse_day
from .progress import (
    DEFAULT_PROGRESSION_MONTHS,
    MAX_PROGRESSION_MONTHS,
    PROGRESSION_SPORTS,
    monthly_progression,
)
from .route_match import overlap, start_lat, track_of
from .units import Quantity, UnitSystem, convert, format_value, to_si, unit_label

MAX_ACTIVITY_ROWS = 20
MIN_ROUTE_OVERLAP = 0.5  # similar_to: share of the route two activities must have in common
SIMILAR_DISTANCE_RATIO = 0.25  # similar_to: candidates within this fraction of the distance
DEFAULT_ACTIVITY_ROWS = 10
MAX_WEEKS = 52
DEFAULT_WEEKS = 12
MAX_CALENDAR_DAYS = 62
MAX_CALENDAR_ROWS = 40
DEFAULT_CALENDAR_DAYS = 14

SPORTS = ("any", "run", "ride", "lift")
_SPORT_TYPES = {"run": RUN_TYPES, "ride": CYCLE_TYPES, "lift": LIFT_TYPES}
_LOG_MODE = {"any": "hybrid", "run": "running", "ride": "cycling", "lift": "lifting"}
# sort_by -> (row field, label); every sort is highest first, with missing values last.
SORTS = {
    "date": ("date", "most recent first"),
    "distance": ("distance_m", "longest distance first"),
    "elevation": ("elevation_gain_m", "most climbing first"),
    "duration": ("moving_time_s", "longest time first"),
}


@dataclass(frozen=True)
class ReadTool:
    name: str
    description: str
    parameters: dict  # JSON Schema object


READ_TOOLS = (
    ReadTool(
        "search_activities",
        "Look up the athlete's logged activities across their WHOLE history (the prompt only "
        "lists the most recent). Use it before saying you cannot find or compare an activity, "
        "and before claiming any superlative (longest, biggest climb, fastest, first, never). "
        "Returns up to 20 rows in the same table format as the training log, with the totals of "
        "the rows shown. 'any' covers every activity except strength sessions; use 'lift' for those. "
        "Distance and elevation ranges are in the units this prompt uses. similar_to finds the "
        "same route done before (by GPS track, any date) and orders by route overlap; privacy "
        "zones trim the ends near home, so overlap is a lower bound.",
        {
            "type": "object",
            "properties": {
                "sport": {
                    "type": "string",
                    "enum": list(SPORTS),
                    "description": "Default any. Ignored with similar_to (the target's sport is used).",
                },
                "date_from": {"type": "string", "description": "Inclusive, YYYY-MM-DD."},
                "date_to": {"type": "string", "description": "Inclusive, YYYY-MM-DD."},
                "name_contains": {
                    "type": "string",
                    "description": "Case-insensitive text in the activity name, e.g. a place.",
                },
                "min_distance": {"type": "number", "description": "Inclusive, athlete's units."},
                "max_distance": {"type": "number", "description": "Inclusive, athlete's units."},
                "min_elevation": {"type": "number", "description": "Inclusive, athlete's units."},
                "max_elevation": {"type": "number", "description": "Inclusive, athlete's units."},
                "similar_to": {
                    "type": "string",
                    "description": (
                        "The activity's date (YYYY-MM-DD; the longest outdoor run or ride that "
                        "day) or its id: return outdoor activities of its sport that share at "
                        f"least {int(MIN_ROUTE_OVERLAP * 100)}% of its route and are within "
                        f"{int(SIMILAR_DISTANCE_RATIO * 100)}% of its distance, most overlap first."
                    ),
                },
                "sort_by": {
                    "type": "string",
                    "enum": list(SORTS),
                    "description": "Default date. Every sort is highest first.",
                },
                "limit": {"type": "integer", "description": f"1-{MAX_ACTIVITY_ROWS}, default 10."},
            },
        },
    ),
    ReadTool(
        "get_weekly_totals",
        "Weekly training totals (activities, hours, distance, climbing), Monday to Sunday, newest "
        "first, for up to 52 weeks. Use it to compare weeks or check a trend beyond what the "
        "prompt's summary shows. The current week is in progress.",
        {
            "type": "object",
            "properties": {
                "weeks": {"type": "integer", "description": f"1-{MAX_WEEKS}, default 12."},
                "sport": {"type": "string", "enum": list(SPORTS), "description": "Default any."},
            },
        },
    ),
    ReadTool(
        "get_progression",
        "Month by month for one sport over up to 60 months, newest first: activities, hours, "
        "distance, climbing, climb per distance, and the month's longest and biggest-climb "
        "activity (date and name). Use it for long-term progress: how capacity and terrain "
        "changed across seasons or years. Months before the sport's first activity are left out.",
        {
            "type": "object",
            "properties": {
                "sport": {"type": "string", "enum": list(PROGRESSION_SPORTS)},
                "months": {
                    "type": "integer",
                    "description": f"1-{MAX_PROGRESSION_MONTHS}, default {DEFAULT_PROGRESSION_MONTHS}.",
                },
            },
            "required": ["sport"],
        },
    ),
    ReadTool(
        "get_calendar",
        "Calendar entries (workouts, races, rest, travel) between two dates, with their ids, "
        "including past ones. Use it to check what is planned or was planned on a date that is "
        "outside the prompt's upcoming-workouts table. Up to 62 days and 40 entries.",
        {
            "type": "object",
            "properties": {
                "date_from": {"type": "string", "description": "YYYY-MM-DD. Default today."},
                "date_to": {
                    "type": "string",
                    "description": f"YYYY-MM-DD. Default {DEFAULT_CALENDAR_DAYS} days after date_from.",
                },
            },
        },
    ),
)
READ_TOOL_NAMES = frozenset(t.name for t in READ_TOOLS)


class _ArgError(ValueError):
    """A bad tool argument; the message is shown to the model."""


def _day_arg(args: dict, key: str) -> date | None:
    raw = args.get(key)
    if raw in (None, ""):
        return None
    day = parse_day(raw)
    if day is None or len(str(raw)) < 10:
        raise _ArgError(f"{key} must be a date like 2026-11-14, got {raw!r}")
    return day


def _int_arg(args: dict, key: str, default: int, low: int, high: int) -> int:
    raw = args.get(key)
    if raw in (None, ""):
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise _ArgError(f"{key} must be a whole number, got {raw!r}") from None
    return max(low, min(high, value))


def _text_arg(args: dict, key: str) -> str:
    value = args.get(key)
    if value is None:
        return ""
    if not isinstance(value, str):
        raise _ArgError(f"{key} must be text, got {value!r}")
    return value.strip()


def _sport_arg(args: dict) -> str:
    sport = _text_arg(args, "sport") or "any"
    if sport not in SPORTS:
        raise _ArgError(f"sport must be one of {', '.join(SPORTS)}, got {sport!r}")
    return sport


def _in_sport(row: dict, sport: str) -> bool:
    kind = row.get("sport_type") or ""
    if sport == "any":
        return kind not in LIFT_TYPES
    return kind in _SPORT_TYPES[sport]


def _num_arg(args: dict, key: str) -> float | None:
    raw = args.get(key)
    if raw in (None, ""):
        return None
    if isinstance(raw, bool):
        raise _ArgError(f"{key} must be a number, got {raw!r}")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise _ArgError(f"{key} must be a number, got {raw!r}") from None
    if not math.isfinite(value) or value < 0:
        raise _ArgError(f"{key} must be a number of 0 or more, got {raw!r}")
    return value


# Range filters: (arg prefix, row field, quantity, slack). Values arrive in the athlete's units,
# usually read off a table that rounds them, so a bound is widened by half a display step (0.1 of
# a distance unit, 1 of an elevation unit) and "min_distance 47.5" still finds the 47.46 shown as
# 47.5.
_RANGES = (
    ("distance", "distance_m", Quantity.DISTANCE, 0.05),
    ("elevation", "elevation_gain_m", Quantity.ELEVATION, 0.5),
)


def _range_filters(args: dict, units: UnitSystem) -> list[tuple[str, float | None, float | None]]:
    """[(row field, low SI, high SI)] for every range the call sets, slack included."""
    out = []
    for name, field, qty, slack in _RANGES:
        low, high = _num_arg(args, f"min_{name}"), _num_arg(args, f"max_{name}")
        if low is not None and high is not None and low > high:
            raise _ArgError(f"min_{name} ({low:g}) is above max_{name} ({high:g})")
        if low is not None or high is not None:
            pad = to_si(slack, qty, units)
            out.append(
                (
                    field,
                    None if low is None else to_si(low, qty, units) - pad,
                    None if high is None else to_si(high, qty, units) + pad,
                )
            )
    return out


def _in_ranges(row: dict, ranges) -> bool:
    for field, low, high in ranges:
        value = row.get(field)
        if value is None:  # a set range excludes rows that lack the value
            return False
        if (low is not None and value < low) or (high is not None and value > high):
            return False
    return True


def _route_sport(row: dict) -> str | None:
    kind = row.get("sport_type") or ""
    for sport, types in _SPORT_TYPES.items():
        if sport != "lift" and kind in types:
            return sport
    return None


def _similar_target(rows: list[dict], ref) -> dict:
    """The activity `similar_to` names: an id, or a date (the training log shows dates, not ids).

    With a date, the longest outdoor run or ride that day, ties to the lowest id.
    """
    day = parse_day(ref) if isinstance(ref, str) and len(ref) >= 10 else None
    if day is not None:
        that_day = [
            r
            for r in rows
            if parse_day(r.get("date")) == day and _route_sport(r) and not _is_virtual(r)
        ]
        if not that_day:
            raise _ArgError(f"no outdoor run or ride on {ref}")
        return min(that_day, key=lambda r: (-(r.get("distance_m") or 0), r.get("id") or 0))
    try:
        target_id = int(ref)
    except (TypeError, ValueError):
        raise _ArgError(
            f"similar_to must be a date like 2026-11-14 or an activity id, got {ref!r}"
        ) from None
    target = next((r for r in rows if r.get("id") == target_id), None)
    if target is None:
        raise _ArgError(f"no activity with id {target_id}; pass its date instead")
    return target


def _similar_pool(rows: list[dict], target_id) -> tuple[dict, str, list[tuple[dict, float]], int]:
    """(target, its sport, [(candidate, overlap)] at or above MIN_ROUTE_OVERLAP, no-track count).

    Candidates are outdoor activities of the target's sport within SIMILAR_DISTANCE_RATIO of its
    distance. Every track is projected around the target's start so the distances compare.
    """
    target = _similar_target(rows, target_id)
    sport = _route_sport(target)
    if sport is None:
        raise _ArgError(
            f"activity {target['id']} is not a run or ride, so it has no route to match"
        )
    ref = start_lat(target)
    target_track = track_of(target, ref) if ref is not None else None
    distance = target.get("distance_m")
    if _is_virtual(target) or target_track is None or not distance:
        raise _ArgError(f"activity {target['id']} has no GPS track to match")
    no_track = 0
    pool = []
    for r in rows:
        if r is target or _route_sport(r) != sport or _is_virtual(r):
            continue
        d = r.get("distance_m") or 0
        if abs(d - distance) > SIMILAR_DISTANCE_RATIO * distance:
            continue
        track = track_of(r, ref)
        if track is None:
            no_track += 1
            continue
        share = overlap(target_track, track)
        if share >= MIN_ROUTE_OVERLAP:
            pool.append((r, share))
    return target, sport, pool, no_track


def _is_virtual(row: dict) -> bool:
    return (row.get("sport_type") or "").startswith("Virtual")


def search_activities(rows: list[dict], args: dict, units: UnitSystem) -> str:
    similar = args.get("similar_to") not in (None, "")
    sport = "any" if similar else _sport_arg(args)  # with similar_to, the target sets the sport
    start, end = _day_arg(args, "date_from"), _day_arg(args, "date_to")
    needle = _text_arg(args, "name_contains").lower()
    sort_by = _text_arg(args, "sort_by") or "date"
    if sort_by not in SORTS:
        raise _ArgError(f"sort_by must be one of {', '.join(SORTS)}, got {sort_by!r}")
    limit = _int_arg(args, "limit", DEFAULT_ACTIVITY_ROWS, 1, MAX_ACTIVITY_ROWS)
    ranges = _range_filters(args, units)

    shares: dict[int, float] = {}
    target = None
    no_track = 0
    if similar:
        target, sport, overlapping, no_track = _similar_pool(rows, args["similar_to"])
        pool = [r for r, _ in overlapping]
        shares = {id(r): s for r, s in overlapping}
    else:
        pool = [r for r in rows if _in_sport(r, sport)]
    matched = []
    for r in pool:
        day = parse_day(r.get("date"))
        if day is None or (start and day < start) or (end and day > end):
            continue
        if needle and needle not in (r.get("name") or "").lower():
            continue
        if not _in_ranges(r, ranges):
            continue
        matched.append(r)

    field, label = SORTS[sort_by]
    # Newest first, then (for the other sorts) a stable sort on the value, highest first and rows
    # without it last, so ties stay newest-first and the order is the same on every call.
    matched.sort(key=lambda r: (str(r.get("date") or ""), r.get("id") or 0), reverse=True)
    if target is not None:
        matched.sort(key=lambda r: -shares[id(r)])
        label = "most route overlap first"
    elif sort_by != "date":
        matched.sort(key=lambda r: (r.get(field) is None, -(r.get(field) or 0)))

    target_text = (
        f"{fmt_day(parse_day(target.get('date')))} {target.get('name') or ''} (id {target['id']})"
        if target is not None
        else ""
    )
    skipped = f" {no_track} without a GPS track were not compared." if no_track else ""
    if not matched:
        filters = [f"sport={sport}"]
        filters += [
            f"{k}={args[k]}"
            for k in (
                "date_from",
                "date_to",
                "name_contains",
                "min_distance",
                "max_distance",
                "min_elevation",
                "max_elevation",
            )
            if args.get(k) not in (None, "")
        ]
        if target is not None and pool:
            return (
                f"{len(pool)} activities share at least {int(MIN_ROUTE_OVERLAP * 100)}% of the "
                f"route of {target_text}, but none passed the other filters "
                f"({', '.join(filters[1:])})."
            )
        if target is not None:
            return (
                f"No other activity shares at least {int(MIN_ROUTE_OVERLAP * 100)}% of the route "
                f"of {target_text}.{skipped} Fall back to distance and elevation ranges for "
                "comparable sessions."
            )
        dates = sorted(str(r["date"])[:10] for r in pool if r.get("date"))
        span = f", {dates[0]} to {dates[-1]}" if dates else ""
        return (
            f"No activities matched ({', '.join(filters)}). Searched {len(pool)} "
            f"{sport if sport != 'any' else 'non-strength'} activities{span}."
        )
    shown = matched[:limit]
    head = f"{len(matched)} matching activities; showing {len(shown)}, {label}."
    if target is not None:
        listed = ", ".join(
            f"{fmt_day(parse_day(r.get('date')))} {round(shares[id(r)] * 100)}%" for r in shown
        )
        head += f"\nCompared by GPS track with {target_text}. Share of the route in common, in table order: {listed}.{skipped}"
    # build_training_log prints oldest-first from a newest-first list, so hand it the reverse.
    table = build_training_log(list(reversed(shown)), _LOG_MODE[sport], units)
    return f"{head}\n{table}"


def progression(rows: list[dict], args: dict, units: UnitSystem, today: date) -> str:
    sport = _text_arg(args, "sport")
    if sport not in PROGRESSION_SPORTS:
        raise _ArgError(f"sport must be one of {', '.join(PROGRESSION_SPORTS)}, got {sport!r}")
    months = _int_arg(args, "months", DEFAULT_PROGRESSION_MONTHS, 1, MAX_PROGRESSION_MONTHS)
    p = monthly_progression(rows, sport, months, today)
    noun = "run" if sport == "run" else "ride"
    if not p.months:
        why = (
            f" ({p.omitted} with a missing, invalid or future date were left out)"
            if p.omitted
            else ""
        )
        return f"No {noun}s logged{why}."
    dist_u = unit_label(Quantity.DISTANCE, units)
    elev_u = unit_label(Quantity.ELEVATION, units)

    def dist(v: float) -> str:
        return format_value(v, Quantity.DISTANCE, units, decimals=1)

    def elev(v: float) -> str:
        return format_value(v, Quantity.ELEVATION, units, decimals=0)

    def peak(pk, fmt) -> str:
        if pk is None:
            return "—"
        return f"{fmt(pk.value)} {fmt_day(parse_day(pk.date))} {pk.name[:24]}"

    lines = [
        f"Monthly {noun} progression, newest first (first {noun} on record: "
        f"{fmt_day(parse_day(p.first_date))}). Hours are moving time; peaks are single "
        "activities (virtual ones included, named). A month with no activity shows 0.",
        f"Month   | Acts | Hours | Distance({dist_u}) | Climb({elev_u}) | Climb/{dist_u} | "
        "Longest | Most climbing",
    ]
    for m in p.months:
        rate = (
            f"{convert(m.climb_m, Quantity.ELEVATION, units) / convert(m.distance_m, Quantity.DISTANCE, units):.0f}"
            if m.distance_m
            else "—"
        )
        note = "  (in progress)" if m.in_progress else ""
        lines.append(
            f"{m.month} | {m.activities:4d} | {m.hours:5.1f} | "
            f"{convert(m.distance_m, Quantity.DISTANCE, units):12.1f} | "
            f"{convert(m.climb_m, Quantity.ELEVATION, units):9.0f} | {rate:>8s} | "
            f"{peak(m.longest, dist)} | {peak(m.most_climb, elev)}{note}"
        )
    if p.omitted:
        lines.append(f"Omitted: {p.omitted} {noun}s with a missing, invalid or future date.")
    return "\n".join(lines)


def weekly_totals(rows: list[dict], args: dict, units: UnitSystem, today: date) -> str:
    sport = _sport_arg(args)
    weeks = _int_arg(args, "weeks", DEFAULT_WEEKS, 1, MAX_WEEKS)
    this_monday = monday_of(today)
    buckets: dict[date, list[dict]] = defaultdict(list)
    for r in rows:
        day = parse_day(r.get("date"))
        if day is not None and day <= today and _in_sport(r, sport):
            buckets[monday_of(day)].append(r)
    dist_u = unit_label(Quantity.DISTANCE, units)
    elev_u = unit_label(Quantity.ELEVATION, units)
    lines = [
        f"Weekly totals, Monday to Sunday, newest first ({sport} activities). "
        "A week with no activity shows 0.",
        f"Week starting  | Activities | Hours | Distance({dist_u}) | Climb({elev_u})",
    ]
    for k in range(weeks):
        monday = this_monday - timedelta(weeks=k)
        acts = buckets.get(monday, [])
        hours = sum((a.get("moving_time_s") or 0) for a in acts) / 3600.0
        dist = convert(sum((a.get("distance_m") or 0) for a in acts), Quantity.DISTANCE, units)
        climb = convert(
            sum((a.get("elevation_gain_m") or 0) for a in acts), Quantity.ELEVATION, units
        )
        note = "  (in progress)" if k == 0 else ""
        lines.append(
            f"{fmt_day(monday):14s} | {len(acts):10d} | {hours:5.1f} | {dist:12.1f} | {climb:8.0f}{note}"
        )
    return "\n".join(lines)


def calendar_range(
    load_plan: Callable[[str, str], list[dict]], args: dict, units: UnitSystem, today: date
) -> str:
    start = _day_arg(args, "date_from") or today
    end = _day_arg(args, "date_to") or start + timedelta(days=DEFAULT_CALENDAR_DAYS)
    if end < start:
        raise _ArgError("date_to is before date_from")
    if (end - start).days > MAX_CALENDAR_DAYS:
        raise _ArgError(f"ask for at most {MAX_CALENDAR_DAYS} days at a time")
    entries = load_plan(start.isoformat(), end.isoformat())
    if not entries:
        return f"No calendar entries from {fmt_day(start)} to {fmt_day(end)}."
    shown = entries[:MAX_CALENDAR_ROWS]
    more = (
        f" Showing the first {len(shown)} of {len(entries)}." if len(entries) > len(shown) else ""
    )
    rows = [plan_row_text(w, units) for w in shown]
    return "\n".join(
        [f"Calendar {fmt_day(start)} to {fmt_day(end)}.{more}", PLAN_TABLE_HEADER, "-" * 88, *rows]
    )


def run_read_tool(
    name: str,
    args: dict,
    *,
    load_activities: Callable[[], list[dict]],
    load_plan: Callable[[str, str], list[dict]],
    units: UnitSystem,
    today: date,
) -> str:
    """The result text for one lookup call. Argument errors are returned, never raised."""
    try:
        if name == "search_activities":
            return search_activities(load_activities(), args, units)
        if name == "get_weekly_totals":
            return weekly_totals(load_activities(), args, units, today)
        if name == "get_progression":
            return progression(load_activities(), args, units, today)
        if name == "get_calendar":
            return calendar_range(load_plan, args, units, today)
    except _ArgError as exc:
        return f"Error: {exc}"
    return f"Unknown tool: {name}"
