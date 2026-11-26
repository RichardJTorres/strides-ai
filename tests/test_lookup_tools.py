"""The coach's read-only lookups: search_activities, get_weekly_totals, get_calendar."""

from datetime import date
from types import SimpleNamespace

import pytest

from strides_ai import lookup_tools as lt
from strides_ai.units import UnitSystem
from tests.test_route_match import LINE, PARALLEL_1KM
from tests.test_route_match import row as track_row

M, I = UnitSystem.METRIC, UnitSystem.IMPERIAL
TODAY = date(2026, 11, 16)  # a Monday


def act(i, d, sport, name, miles, feet, hours, **kw):
    row = {
        "id": i,
        "date": d,
        "sport_type": sport,
        "name": name,
        "distance_m": miles * 1609.34 if miles is not None else None,
        "elevation_gain_m": feet / 3.28084 if feet is not None else None,
        "moving_time_s": int(hours * 3600) if hours is not None else None,
        "avg_pace_s_per_km": 400.0,
        "avg_hr": 140,
        "max_hr": 160,
        "avg_cadence": 80,
        "suffer_score": 50,
        "perceived_exertion": None,
    }
    row.update(kw)
    return row


# The athlete's real long-climb days (the coach once claimed 3,862 ft was the biggest).
SQUAK_50K = act(1, "2026-04-18", "Run", "Squak Mountain 50k", 31.0, 8379, 9.9)
PORT_ANGELES = act(2, "2025-10-04", "Ride", "Port Angeles to Crescent lake", 41.8, 3873, 5.7)
NUTMEG = act(3, "2026-10-24", "Ride", "Nutmeg Day2 - Mixed Mild Nuts", 47.5, 3862, 6.0)
SQUAK_12 = act(4, "2025-11-29", "Run", "Squak 12 miler", 12.7, 3594, 3.3)
NO_CLIMB = act(5, "2026-11-10", "VirtualRide", "Zwift spin", 10.1, None, 0.7)
LIFT = act(
    6,
    "2026-11-11",
    "WeightTraining",
    "Legs",
    None,
    None,
    1.0,
    total_sets=12,
    total_volume_kg=9000.0,
)
ROWS = [SQUAK_50K, PORT_ANGELES, NUTMEG, SQUAK_12, NO_CLIMB, LIFT]


def names(text):
    """The activities in `text`, in the order they appear in it."""
    found = [
        n
        for n in ("Squak Mountain 50k", "Port Angeles", "Nutmeg", "Squak 12", "Zwift", "Legs")
        if n in text
    ]
    return sorted(found, key=text.index)


# ── search_activities ─────────────────────────────────────────────────────────


def test_most_climbing_first_finds_the_50k_not_the_3862_ft_ride():
    out = lt.search_activities(ROWS, {"sort_by": "elevation", "limit": 3}, I)
    assert names(out) == ["Squak Mountain 50k", "Port Angeles", "Nutmeg"]
    assert "8379" in out and "3873" in out and "Zwift" not in out
    assert "5 matching activities; showing 3, most climbing first." in out  # the lift is not 'any'


def test_missing_values_sort_last_and_lifts_are_left_out_of_any():
    out = lt.search_activities(ROWS, {"sort_by": "elevation", "limit": 20}, I)
    assert out.index("Squak 12") < out.index("Zwift")
    assert "Legs" not in out


def test_sport_filters_name_and_dates():
    assert names(lt.search_activities(ROWS, {"sport": "ride"}, M)) == [
        "Zwift",
        "Nutmeg",
        "Port Angeles",
    ]
    squak = lt.search_activities(ROWS, {"name_contains": "SQUAK"}, M)
    assert names(squak) == ["Squak Mountain 50k", "Squak 12"]
    window = lt.search_activities(ROWS, {"date_from": "2026-01-01", "date_to": "2026-10-31"}, M)
    assert names(window) == ["Nutmeg", "Squak Mountain 50k"]
    assert "Legs" in lt.search_activities(ROWS, {"sport": "lift"}, M)


def test_default_order_is_newest_first_and_deterministic():
    out = lt.search_activities(ROWS, {}, M)
    assert names(out) == ["Zwift", "Nutmeg", "Squak Mountain 50k", "Squak 12", "Port Angeles"]
    again = lt.search_activities(list(reversed(ROWS)), {}, M)
    assert out == again


def test_table_has_weekday_dates_and_a_footer_scoped_to_the_rows_shown():
    out = lt.search_activities(ROWS, {"name_contains": "squak mountain"}, M)
    assert "Sat 2026-04-18" in out
    assert "(the rows above only)" in out


def test_no_match_says_what_was_searched():
    out = lt.search_activities(ROWS, {"sport": "run", "name_contains": "tahoe"}, M)
    assert out.startswith("No activities matched (sport=run, name_contains=tahoe).")
    assert "Searched 2 run activities, 2025-11-29 to 2026-04-18." in out


def test_limit_is_clamped_not_rejected():
    many = [act(100 + i, f"2026-01-{i + 1:02d}", "Run", f"Run {i}", 5, 100, 0.8) for i in range(30)]
    assert "showing 20" in lt.search_activities(many, {"limit": 999}, M)
    assert "showing 1," in lt.search_activities(many, {"limit": 0}, M)


@pytest.mark.parametrize(
    "args, fragment",
    [
        ({"sport": "swim"}, "sport must be one of"),
        ({"sort_by": "speed"}, "sort_by must be one of"),
        ({"date_from": "tomorrow"}, "date_from must be a date like 2026-11-14"),
        ({"limit": "lots"}, "limit must be a whole number"),
        ({"name_contains": 5}, "name_contains must be text"),
        ({"sort_by": ["date"]}, "sort_by must be text"),
        ({"sport": {"a": 1}}, "sport must be text"),
    ],
)
def test_bad_arguments_come_back_as_error_text(args, fragment):
    out = lt.run_read_tool(
        "search_activities",
        args,
        load_activities=lambda: ROWS,
        load_plan=lambda a, b: [],
        units=M,
        today=TODAY,
    )
    assert out.startswith("Error: ") and fragment in out


# ── range filters ─────────────────────────────────────────────────────────────


def test_ranges_are_in_the_athletes_units_and_exclude_rows_without_the_value():
    assert names(lt.search_activities(ROWS, {"sport": "ride", "min_distance": 42}, I)) == ["Nutmeg"]
    # 3594 ft is just under; the Zwift ride has no climb and is left out, not treated as 0.
    out = lt.search_activities(ROWS, {"min_elevation": 3600}, I)
    assert names(out) == ["Nutmeg", "Squak Mountain 50k", "Port Angeles"]
    assert names(lt.search_activities(ROWS, {"max_distance": 25}, M)) == ["Zwift", "Squak 12"]
    assert names(lt.search_activities(ROWS, {"max_elevation": 1100}, M)) == ["Squak 12"]
    both = {"min_distance": 40, "max_distance": 45, "min_elevation": 3000, "max_elevation": 4000}
    assert names(lt.search_activities(ROWS, both, I)) == ["Port Angeles"]


def test_a_displayed_value_matches_its_own_bound():
    # The coach reads 47.5 mi in the table and asks for exactly that.
    out = lt.search_activities(ROWS, {"min_distance": 47.5, "max_distance": 47.5}, I)
    assert names(out) == ["Nutmeg"]
    # The slack is half a display step, not more: 47.6 mi is a different ride.
    assert "No activities matched" in lt.search_activities(ROWS, {"min_distance": 47.6}, I)
    assert names(lt.search_activities(ROWS, {"max_elevation": 3861}, I)) == ["Squak 12"]


def test_no_range_match_echoes_the_filters():
    out = lt.search_activities(ROWS, {"sport": "ride", "min_distance": 100}, I)
    assert out.startswith("No activities matched (sport=ride, min_distance=100)")


@pytest.mark.parametrize(
    "args, fragment",
    [
        ({"min_distance": "far"}, "min_distance must be a number"),
        ({"max_elevation": True}, "max_elevation must be a number"),
        ({"min_distance": -1}, "min_distance must be a number of 0 or more"),
        ({"min_distance": float("nan")}, "min_distance must be a number of 0 or more"),
        ({"min_elevation": 500, "max_elevation": 100}, "min_elevation (500) is above"),
        (
            {"similar_to": "the long one"},
            "similar_to must be a date like 2026-11-14 or an activity id",
        ),
        ({"similar_to": "2020-01-01"}, "no outdoor run or ride on 2020-01-01"),
        ({"similar_to": 999}, "no activity with id 999"),
        ({"similar_to": 6}, "is not a run or ride"),
        ({"similar_to": 1}, "has no GPS track"),
    ],
)
def test_bad_filter_arguments_come_back_as_error_text(args, fragment):
    out = lt.run_read_tool(
        "search_activities",
        args,
        load_activities=lambda: ROWS,
        load_plan=lambda a, b: [],
        units=I,
        today=TODAY,
    )
    assert out.startswith("Error: ") and fragment in out


# ── similar_to ────────────────────────────────────────────────────────────────

# A 6.5 km loop: the 4 km line, then 2.5 km north. BRANCH shares the line, then turns south.
LOOP = LINE + [(47.5 + 0.0045 * i, LINE[-1][1]) for i in range(1, 6)]
BRANCH = LINE + [(47.5 - 0.0045 * i, LINE[-1][1]) for i in range(1, 6)]


def tracked(i, d, name, points, miles=12.0, sport="Ride", **kw):
    return {**act(i, d, sport, name, miles, 1500, 1.2, **kw), **track_row(points)}


ROUTES = [
    tracked(10, "2026-11-24", "Kent loop", LOOP),
    tracked(11, "2025-07-19", "Kent loop last summer", LOOP),
    tracked(12, "2026-08-24", "Kent loop reversed", list(reversed(LOOP))),
    tracked(13, "2026-09-13", "Kent, other finish", BRANCH, miles=11.0),
    tracked(14, "2026-06-01", "Same roads, much longer", LOOP, miles=30.0),
    tracked(15, "2026-05-01", "Other side of town", PARALLEL_1KM),
    tracked(16, "2026-04-01", "Zwift on the loop", LOOP, sport="VirtualRide"),
    tracked(17, "2026-03-01", "Run on the loop", LOOP, sport="Run"),
    act(18, "2026-02-01", "Ride", "No GPS", 12.0, 1500, 1.2),
]


def route_names(text):
    rows = [
        line
        for line in text.splitlines()
        if line[:4] in ("Mon ", "Tue ", "Wed ", "Thu ", "Fri ", "Sat ", "Sun ")
    ]
    return [line.split("|")[1].strip() for line in rows]


def test_similar_to_finds_the_same_route_in_either_direction_most_overlap_first():
    out = lt.search_activities(ROUTES, {"similar_to": 10}, I)
    # 100% ties stay newest first; the ride sharing ~60% clears 50%; the target is not listed.
    assert route_names(out) == ["Kent loop reversed", "Kent loop last summer", "Kent, other finish"]
    assert "Compared by GPS track with Tue 2026-11-24 Kent loop (id 10)" in out
    assert "Mon 2026-08-24 100%, Sat 2025-07-19 100%, Sun 2026-09-13" in out
    assert "1 without a GPS track were not compared." in out
    # Never: a much longer ride, a parallel road, a virtual ride, another sport.
    for absent in ("much longer", "Other side", "Zwift", "Run on the loop"):
        assert absent not in out


def test_similar_to_takes_the_date_the_training_log_shows():
    # The coach sees dates, not ids. On a date it takes the longest outdoor run or ride that day.
    short = tracked(19, "2026-11-24", "Coffee spin", PARALLEL_1KM, miles=3.0)
    zwift = tracked(20, "2026-11-24", "Zwift", LOOP, miles=40.0, sport="VirtualRide")
    out = lt.search_activities(ROUTES + [short, zwift], {"similar_to": "2026-11-24"}, I)
    assert "Compared by GPS track with Tue 2026-11-24 Kent loop (id 10)" in out
    assert route_names(out)[0] == "Kent loop reversed"
    assert lt.search_activities(ROUTES, {"similar_to": "10"}, I) == lt.search_activities(
        ROUTES, {"similar_to": 10}, I
    )


def test_similar_to_combines_with_dates_and_ranges_and_ignores_sport():
    out = lt.search_activities(
        ROUTES, {"similar_to": 10, "date_to": "2025-12-31", "sport": "run"}, I
    )
    assert route_names(out) == ["Kent loop last summer"]
    out = lt.search_activities(ROUTES, {"similar_to": 10, "max_distance": 11.5}, I)
    assert route_names(out) == ["Kent, other finish"]


def test_similar_to_with_no_repeat_says_so_and_points_to_ranges():
    out = lt.search_activities(ROUTES, {"similar_to": 15}, I)
    assert out.startswith("No other activity shares at least 50% of the route")
    assert "distance and elevation ranges" in out


def test_similar_to_says_when_the_filters_removed_the_route_repeats():
    out = lt.search_activities(ROUTES, {"similar_to": 10, "date_from": "2027-01-01"}, I)
    assert out.startswith("3 activities share at least 50% of the route of Tue 2026-11-24")
    assert "none passed the other filters (date_from=2027-01-01)" in out


def test_similar_to_does_not_validate_the_ignored_sport():
    out = lt.search_activities(ROUTES, {"similar_to": 10, "sport": "swim"}, I)
    assert "Kent loop reversed" in out


def test_a_virtual_target_has_no_track_to_match():
    out = lt.run_read_tool(
        "search_activities",
        {"similar_to": 16},
        load_activities=lambda: ROUTES,
        load_plan=lambda a, b: [],
        units=I,
        today=TODAY,
    )
    assert out == "Error: activity 16 has no GPS track to match"


# ── get_progression ───────────────────────────────────────────────────────────


def progression(args, rows=ROWS, units=I):
    return lt.run_read_tool(
        "get_progression",
        args,
        load_activities=lambda: rows,
        load_plan=lambda a, b: [],
        units=units,
        today=TODAY,
    )


def test_progression_table_in_the_athletes_units():
    out = progression({"sport": "ride", "months": 14})
    lines = out.splitlines()
    assert lines[0].startswith(
        "Monthly ride progression, newest first (first ride on record: Sat 2025-10-04)"
    )
    assert lines[1].startswith("Month   | Acts | Hours | Distance(mi) | Climb(ft) | Climb/mi |")
    months = [line.split(" |")[0] for line in lines[2:]]
    assert months[0] == "2026-11" and months[-1] == "2025-10" and len(months) == 14
    assert "(in progress)" in lines[2]
    oct26 = next(line for line in lines if line.startswith("2026-10"))
    assert "47.5 mi Sat 2026-10-24 Nutmeg Day2 - Mixed Mild" in oct26
    assert "3862 ft Sat 2026-10-24" in oct26
    empty = next(line for line in lines if line.startswith("2026-09"))
    assert "|    0 |   0.0 |" in empty and empty.endswith("— | —")


def test_progression_metric_and_runs():
    out = progression({"sport": "run"}, units=M)
    assert "Distance(km) | Climb(m) | Climb/km" in out
    assert "49.9 km Sat 2026-04-18 Squak Mountain 50k" in out


@pytest.mark.parametrize(
    "args, fragment",
    [
        ({}, "sport must be one of run, ride"),
        ({"sport": "lift"}, "sport must be one of run, ride"),
        ({"sport": "ride", "months": "many"}, "months must be a whole number"),
    ],
)
def test_progression_bad_arguments(args, fragment):
    out = progression(args)
    assert out.startswith("Error: ") and fragment in out


def test_progression_with_no_activities_of_the_sport():
    assert progression({"sport": "run"}, rows=[NUTMEG]) == "No runs logged."
    undated = {**SQUAK_12, "date": "someday"}
    out = progression({"sport": "run"}, rows=[undated])
    assert out == "No runs logged (1 with a missing, invalid or future date were left out)."


# ── get_weekly_totals ─────────────────────────────────────────────────────────


def test_weekly_totals_values_zero_weeks_and_the_current_week():
    rows = [
        act(10, "2026-11-09", "Ride", "a", 10, 1000, 1.0),
        act(11, "2026-11-15", "Run", "b", 5, 500, 0.5),
        act(12, "2026-11-16", "Run", "today", 2, 100, 0.25),
        act(13, "2026-11-20", "Run", "future", 9, 900, 9.0),  # not happened yet
    ]
    out = lt.weekly_totals(rows, {"weeks": 3}, I, TODAY)
    lines = out.splitlines()
    assert "Distance(mi)" in lines[1] and "Climb(ft)" in lines[1]
    this_week, last_week, before = lines[2], lines[3], lines[4]
    assert "Mon 2026-11-16" in this_week and "(in progress)" in this_week
    assert " 1 |" in this_week and "0.2" in this_week and "2.0" in this_week
    assert "Mon 2026-11-09" in last_week and " 2 |" in last_week and "1.5" in last_week
    assert "15.0" in last_week  # 10 mi + 5 mi
    assert " 0 |" in before and "0.0" in before  # a real zero week is shown as 0


def test_weekly_totals_sport_filter_and_clamp():
    rows = [
        act(10, "2026-11-09", "Ride", "a", 10, 1000, 1.0),
        act(11, "2026-11-10", "Run", "b", 5, 0, 0.5),
    ]
    runs = lt.weekly_totals(rows, {"sport": "run", "weeks": 2}, M, TODAY).splitlines()
    assert "8.0" in runs[3]  # 5 mi in km
    assert len(lt.weekly_totals(rows, {"weeks": 500}, M, TODAY).splitlines()) == 2 + 52


# ── get_calendar ──────────────────────────────────────────────────────────────


def plan(i, d, kind="workout", wtype="Easy Run", **kw):
    row = {
        "id": i,
        "date": d,
        "kind": kind,
        "workout_type": wtype,
        "title": None,
        "distance_km": 8.0,
        "elevation_m": None,
        "duration_min": 40,
        "intensity": "easy",
        "structure_json": None,
        "goal_time_s": None,
        "goal_text": None,
        "priority": None,
    }
    row.update(kw)
    return row


def calendar(args, entries):
    seen = {}

    def load(a, b):
        seen["range"] = (a, b)
        return entries

    return lt.calendar_range(load, args, M, TODAY), seen["range"] if "range" in seen else None


def test_calendar_defaults_to_two_weeks_from_today_and_shows_ids_weekdays_and_races():
    entries = [
        plan(66, "2026-11-17"),
        plan(88, "2026-12-12", "race", "Running Race", title="Evergreen Grinder", priority="A"),
    ]
    text, rng = calendar({}, entries)
    assert rng == ("2026-11-16", "2026-11-30")
    assert "Calendar Mon 2026-11-16 to Mon 2026-11-30." in text
    assert "66    | Tue 2026-11-17" in text and "88    | Sat 2026-12-12" in text
    assert "race: Evergreen Grinder, priority A" in text


def test_calendar_empty_range_and_row_cap_and_errors():
    assert (
        "No calendar entries"
        in calendar({"date_from": "2026-12-01", "date_to": "2026-12-03"}, [])[0]
    )
    many = [plan(i, "2026-11-17") for i in range(50)]
    assert "Showing the first 40 of 50." in calendar({}, many)[0]
    with pytest.raises(lt._ArgError, match="before date_from"):
        calendar({"date_from": "2026-11-20", "date_to": "2026-11-19"}, [])
    with pytest.raises(lt._ArgError, match="at most 62 days"):
        calendar({"date_from": "2026-01-01", "date_to": "2026-06-01"}, [])


# ── specs and backend wiring ──────────────────────────────────────────────────


def test_specs_are_well_formed_and_unique():
    assert [t.name for t in lt.READ_TOOLS] == [
        "search_activities",
        "get_weekly_totals",
        "get_progression",
        "get_calendar",
    ]
    assert lt.READ_TOOL_NAMES == {t.name for t in lt.READ_TOOLS}
    for tool in lt.READ_TOOLS:
        assert tool.parameters["type"] == "object" and tool.description
        # Every lookup works with no arguments, except that a progression needs its sport.
        expected = ["sport"] if tool.name == "get_progression" else None
        assert tool.parameters.get("required") == expected


def test_every_backend_offers_all_the_lookups():
    from strides_ai.backends import claude, gemini, ollama, openai

    def tool_names(tool):
        if isinstance(tool, dict):
            return tool.get("name") or tool["function"]["name"]
        return tool.function_declarations[0].name

    for module in (claude, openai, ollama, gemini):
        assert {tool_names(t) for t in module.READ_TOOLS} == lt.READ_TOOL_NAMES, module.__name__

    backend = claude.ClaudeBackend("sk-test", [])
    offered = {tool_names(t) for t in backend._tool_definitions()}
    assert offered >= lt.READ_TOOL_NAMES | {"save_memory", "update_profile", "update_training_plan"}


def test_gemini_accepts_the_json_schema_declarations():
    from google.genai import types

    from strides_ai.backends import gemini

    config = types.GenerateContentConfig(tools=gemini.READ_TOOLS)
    declared = [t.function_declarations[0] for t in config.tools]
    assert declared[0].parameters_json_schema["properties"]["sort_by"]["enum"] == list(lt.SORTS)


def _stub():
    return SimpleNamespace(
        _check_cancelled=lambda: None, _budget=SimpleNamespace(tool=lambda a: None)
    )


def test_backend_dispatches_a_lookup_against_the_database(mocker):
    from strides_ai.backends.base import BaseBackend

    mocker.patch("strides_ai.backends.base.db.get_all_activities", return_value=ROWS)
    mocker.patch("strides_ai.backends.base.db.get_unit_system", return_value=I)
    stub = _stub()
    stub._execute_read_tool = lambda n, a: BaseBackend._execute_read_tool(stub, n, a)
    out = BaseBackend._run_tool(
        stub, "search_activities", {"sort_by": "elevation", "limit": 1}, [], []
    )
    assert "Squak Mountain 50k" in out and "8379" in out
    assert BaseBackend._run_tool(stub, "not_a_tool", {}, [], []) is None


def test_a_failing_lookup_returns_text_instead_of_ending_the_turn(mocker):
    from strides_ai.backends.base import BaseBackend

    mocker.patch("strides_ai.backends.base.db.get_all_activities", side_effect=RuntimeError("db"))
    mocker.patch("strides_ai.backends.base.db.get_unit_system", return_value=M)
    out = BaseBackend._execute_read_tool(_stub(), "search_activities", {})
    assert out.startswith("Error: the lookup failed (RuntimeError)")
