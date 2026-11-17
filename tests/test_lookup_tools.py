"""The coach's read-only lookups: search_activities, get_weekly_totals, get_calendar."""

from datetime import date
from types import SimpleNamespace

import pytest

from strides_ai import lookup_tools as lt
from strides_ai.units import UnitSystem

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
        "get_calendar",
    ]
    assert lt.READ_TOOL_NAMES == {t.name for t in lt.READ_TOOLS}
    for tool in lt.READ_TOOLS:
        assert tool.parameters["type"] == "object" and tool.description
        assert "required" not in tool.parameters  # every lookup works with no arguments


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
