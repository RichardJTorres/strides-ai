"""Read-only lookup tools for the chat coach: find activities, weekly totals, calendar entries.

The coach's prompt carries only the 30 most recent activities and aggregates of older ones, so it
used to guess ("your longest climb is 3,862 ft") or give up ("I can't search your runs"). These
tools let it check. They are specified once here (`READ_TOOLS`) and rendered into each provider's
format by the backend modules; `run_read_tool` executes one and returns the text for the model.

Pure apart from the loaders the caller passes in: `today` and `units` are parameters, results are
deterministic and bounded (a few thousand tokens at most), and every argument problem comes back
as an `Error: ...` string the model can act on, never as an exception.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Callable

from .activity_types import CYCLE_TYPES, LIFT_TYPES, RUN_TYPES
from .analytics.aggregation import monday_of
from .coach import PLAN_TABLE_HEADER, build_training_log, plan_row_text
from .dates import fmt_day, parse_day
from .units import Quantity, UnitSystem, convert, unit_label

MAX_ACTIVITY_ROWS = 20
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
        "the rows shown. 'any' covers every activity except strength sessions; use 'lift' for those.",
        {
            "type": "object",
            "properties": {
                "sport": {"type": "string", "enum": list(SPORTS), "description": "Default any."},
                "date_from": {"type": "string", "description": "Inclusive, YYYY-MM-DD."},
                "date_to": {"type": "string", "description": "Inclusive, YYYY-MM-DD."},
                "name_contains": {
                    "type": "string",
                    "description": "Case-insensitive text in the activity name, e.g. a place.",
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


def search_activities(rows: list[dict], args: dict, units: UnitSystem) -> str:
    sport = _sport_arg(args)
    start, end = _day_arg(args, "date_from"), _day_arg(args, "date_to")
    needle = _text_arg(args, "name_contains").lower()
    sort_by = _text_arg(args, "sort_by") or "date"
    if sort_by not in SORTS:
        raise _ArgError(f"sort_by must be one of {', '.join(SORTS)}, got {sort_by!r}")
    limit = _int_arg(args, "limit", DEFAULT_ACTIVITY_ROWS, 1, MAX_ACTIVITY_ROWS)

    pool = [r for r in rows if _in_sport(r, sport)]
    matched = []
    for r in pool:
        day = parse_day(r.get("date"))
        if day is None or (start and day < start) or (end and day > end):
            continue
        if needle and needle not in (r.get("name") or "").lower():
            continue
        matched.append(r)

    field, label = SORTS[sort_by]
    # Newest first, then (for the other sorts) a stable sort on the value, highest first and rows
    # without it last, so ties stay newest-first and the order is the same on every call.
    matched.sort(key=lambda r: (str(r.get("date") or ""), r.get("id") or 0), reverse=True)
    if sort_by != "date":
        matched.sort(key=lambda r: (r.get(field) is None, -(r.get(field) or 0)))

    if not matched:
        filters = [f"sport={sport}"]
        filters += [
            f"{k}={args[k]}" for k in ("date_from", "date_to", "name_contains") if args.get(k)
        ]
        dates = sorted(str(r["date"])[:10] for r in pool if r.get("date"))
        span = f", {dates[0]} to {dates[-1]}" if dates else ""
        return (
            f"No activities matched ({', '.join(filters)}). Searched {len(pool)} "
            f"{sport if sport != 'any' else 'non-strength'} activities{span}."
        )
    shown = matched[:limit]
    head = f"{len(matched)} matching activities; showing {len(shown)}, {label}."
    # build_training_log prints oldest-first from a newest-first list, so hand it the reverse.
    table = build_training_log(list(reversed(shown)), _LOG_MODE[sport], units)
    return f"{head}\n{table}"


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
        if name == "get_calendar":
            return calendar_range(load_plan, args, units, today)
    except _ArgError as exc:
        return f"Error: {exc}"
    return f"Unknown tool: {name}"
