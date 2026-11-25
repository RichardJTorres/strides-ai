"""Tests for strides_ai.training_state — projection, weekly ramp, conflicts and guardrails."""

from datetime import date, timedelta

import pytest

from tests.plan_helpers import save_planned_workout, save_races
from strides_ai.analytics import cardio
from strides_ai.analytics.adapters import to_cardio_analytics
from strides_ai.training_state import (
    ACWR_HIGH,
    apply_changes,
    build_training_state,
    check_plan_changes,
    week_series,
)
from strides_ai.units import UnitSystem

TODAY = date(2026, 6, 3)  # Wednesday
START = date(2026, 3, 9)


def run_row(i: int, d: date, km: float = 10.0) -> dict:
    return {
        "id": i,
        "source": "strava",
        "sport_type": "Run",
        "date": d.isoformat(),
        "name": "Run",
        "moving_time_s": 3600,
        "distance_m": km * 1000,
    }


def steady_rows(km: float = 10.0) -> list[dict]:
    rows, d, i = [], START, 1
    while d <= TODAY:
        rows.append(run_row(i, d, km))
        d += timedelta(days=2)
        i += 1
    return rows


def plan(d: date, minutes: float | None, wtype: str = "Easy Run", intensity: str | None = "easy"):
    return {
        "date": d.isoformat(),
        "workout_type": wtype,
        "distance_km": None,  # load ignores distance: only the planned duration counts
        "duration_min": minutes,
        "intensity": intensity,
    }


def state(rows=None, plan_rows=None, prefs=None, units=UnitSystem.METRIC, mode="running"):
    return build_training_state(
        steady_rows() if rows is None else rows, plan_rows or [], prefs or {}, mode, units, TODAY
    )


def test_load_is_none_under_28_days_of_history():
    s = state(rows=[run_row(1, TODAY - timedelta(days=10))])
    assert s.load == {"ctl": None, "atl": None, "ratio": None}
    assert s.projection == []


def test_current_load_matches_analytics_chart():
    s = state()
    last = cardio.compute_atl_ctl(to_cardio_analytics(steady_rows()), "km", TODAY).data[-1]
    assert last.ctl > 0
    assert s.load == {"ctl": last.ctl, "atl": last.atl, "ratio": last.ratio}


def test_projection_follows_planned_volume():
    rest = state()
    hard = state(plan_rows=[plan(TODAY + timedelta(days=i), 180.0) for i in range(1, 6)])
    assert hard.projection[4]["atl"] > rest.projection[4]["atl"]
    assert hard.projection[0]["planned"] == pytest.approx(3.0)  # 180 min = 3 h
    assert len(rest.projection) == 28


def test_deterministic():
    plan_rows = [plan(TODAY + timedelta(days=2), 72.0)]
    assert state(plan_rows=plan_rows).to_dict() == state(plan_rows=plan_rows).to_dict()


def test_load_is_the_same_in_every_unit_system_and_reported_in_hours():
    plan_rows = [plan(TODAY + timedelta(days=1), 90.0)]
    metric = state(plan_rows=plan_rows)
    imperial = state(plan_rows=plan_rows, units=UnitSystem.IMPERIAL)
    assert metric.to_dict() == imperial.to_dict()
    assert metric.unit == "h"
    assert metric.projection[0]["planned"] == pytest.approx(1.5)


def test_distance_alone_does_not_count_as_load():
    row = {**plan(TODAY + timedelta(days=1), None), "distance_km": 40.0}
    s = state(plan_rows=[row])
    assert s.projection[0]["planned"] == 0
    assert s.unscored_planned == [(TODAY + timedelta(days=1)).isoformat()]


def test_planned_strength_counts_as_load_in_every_mode_but_yoga_does_not():
    """Strength is scored by presence (sport-ambiguous), so its planned hours are load in running
    and cycling mode too; Yoga is unscored and contributes nothing."""
    day = TODAY + timedelta(days=2)
    for mode in ("running", "cycling", "hybrid"):
        strength = state(plan_rows=[plan(day, 45.0, "Strength", "moderate")], mode=mode)
        assert strength.projection[1]["planned"] == pytest.approx(0.75), mode
        assert strength.unscored_planned == []
    yoga = state(plan_rows=[plan(day, 45.0, "Yoga", "easy")])
    assert yoga.projection[1]["planned"] == 0


def test_race_counts_by_goal_time_and_unscored_without_one():
    day = TODAY + timedelta(days=3)
    race = {**plan(day, None, "Running Race", "hard"), "kind": "race", "goal_time_s": 5400}
    assert state(plan_rows=[race]).projection[2]["planned"] == pytest.approx(1.5)
    no_goal = {**race, "goal_time_s": None}
    s = state(plan_rows=[no_goal])
    assert s.projection[2]["planned"] == 0 and s.unscored_planned == [day.isoformat()]


def test_volume_less_planned_workouts_are_listed_not_guessed():
    s = state(plan_rows=[plan(TODAY + timedelta(days=1), None)])
    assert s.unscored_planned == [(TODAY + timedelta(days=1)).isoformat()]
    assert s.projection[0]["planned"] == 0


def test_rest_and_other_sport_do_not_count_in_running_mode():
    rows = [
        plan(TODAY + timedelta(days=1), 300.0, "Rest", "rest"),
        plan(TODAY + timedelta(days=2), 480.0, "Long Ride"),
    ]
    s = state(plan_rows=rows)
    assert all(p["planned"] == 0 for p in s.projection[:3])
    assert state(plan_rows=rows, mode="cycling").projection[1]["planned"] == pytest.approx(8.0)


def test_big_planned_week_flags_ramp_but_the_ratio_is_never_a_violation():
    rows = [plan(TODAY + timedelta(days=i), 240.0) for i in range(1, 8)]
    s = state(plan_rows=rows)
    kinds = {c["kind"] for c in s.conflicts}
    assert "ramp_high" in kinds
    assert "ratio_breach" not in kinds  # the ratio is context (Impellizzeri 2020), not a guardrail
    assert max(p["ratio"] for p in s.projection) > ACWR_HIGH  # still computed and projected


def test_conflicts_on_blocked_and_race_days():
    blocked = TODAY + timedelta(days=3)
    race = TODAY + timedelta(days=5)
    prefs = {
        "blocked_days": [blocked.isoformat()],
        "races": [{"date": race.isoformat(), "name": "10K"}],
    }
    rows = [
        plan(blocked, 45.0),
        plan(race, 90.0, "Tempo Run"),  # longer than a shakeout
        plan(race + timedelta(days=1), 0, "Rest", "rest"),
    ]
    s = state(plan_rows=rows, prefs=prefs)
    hard = {(c["kind"], c["date"]) for c in s.conflicts if c["hard"]}
    assert hard == {("blocked_day", blocked.isoformat()), ("race_day", race.isoformat())}
    assert s.constraints["next_race"]["days_out"] == 5


def test_race_workout_on_race_day_is_not_a_conflict():
    race = TODAY + timedelta(days=5)
    prefs = {"races": [{"date": race.isoformat(), "name": "10K"}]}
    s = state(plan_rows=[plan(race, 60.0, "Running Race", "hard")], prefs=prefs)
    assert not [c for c in s.conflicts if c["kind"] == "race_day"]


def test_recovery_week_flag_after_rising_weeks():
    rows = []
    for w, minutes in enumerate([240, 300, 360, 420]):
        monday = TODAY - timedelta(days=TODAY.weekday()) + timedelta(weeks=w + 1)
        rows.append(plan(monday + timedelta(days=4), float(minutes)))
    flagged = [wk for wk in state(plan_rows=rows).weeks if "no_recovery_week" in wk["flags"]]
    assert flagged


def test_check_plan_changes_rejects_blocked_and_race_days():
    blocked = TODAY + timedelta(days=2)
    prefs = {"blocked_days": [blocked.isoformat()]}
    changes = {
        "create": [{"date": blocked.isoformat(), "workout_type": "Easy Run", "duration_min": 30}]
    }
    out = check_plan_changes(steady_rows(), [], prefs, "running", UnitSystem.METRIC, TODAY, changes)
    assert [(v.kind, v.hard) for v in out] == [("blocked_day", True)]
    # Rest is allowed on a blocked day.
    rest = {
        "create": [
            {
                "date": blocked.isoformat(),
                "kind": "rest",
                "workout_type": "Rest",
                "intensity": "rest",
            }
        ]
    }
    assert not check_plan_changes(
        steady_rows(), [], prefs, "running", UnitSystem.METRIC, TODAY, rest
    )


def test_check_plan_changes_warns_on_new_ramp_but_not_existing():
    big = {
        "create": [
            {
                "date": (TODAY + timedelta(days=i)).isoformat(),
                "workout_type": "Easy Run",
                "duration_min": 240.0,
            }
            for i in range(1, 8)
        ]
    }
    out = check_plan_changes(steady_rows(), [], {}, "running", UnitSystem.METRIC, TODAY, big)
    assert "ramp_high" in {v.kind for v in out}
    assert not any(v.hard for v in out)
    # Applying the same overload on top of a plan that already contains it adds nothing new.
    existing = apply_changes([], big)
    again = check_plan_changes(
        steady_rows(), existing, {}, "running", UnitSystem.METRIC, TODAY, {"create": []}
    )
    assert again == []


def test_threshold_constant_is_shared():
    assert state().thresholds["acwr_high"] == ACWR_HIGH


# ── update_training_plan guardrails ─────────────────────────────────────────────


def _exec_plan(mocker, args, prefs=None):
    from types import SimpleNamespace

    from strides_ai.backends.base import BaseBackend

    mocker.patch("strides_ai.backends.base.db.get_all_activities", return_value=steady_rows())
    mocker.patch("strides_ai.backends.base.db.get_training_plan", return_value=[])
    mocker.patch("strides_ai.backends.base.db.get_calendar_prefs", return_value=prefs or {})
    mocker.patch("strides_ai.backends.base.db.get_unit_system", return_value=UnitSystem.METRIC)
    save = mocker.patch(
        "strides_ai.backends.base.db.apply_calendar_changes",
        return_value={"created": [101], "updated": [], "deleted": []},
    )
    stub = SimpleNamespace(
        _check_cancelled=lambda: None,
        _budget=SimpleNamespace(tool=lambda a: None, changes=[]),
    )
    return BaseBackend._execute_update_training_plan(stub, args), save


def test_tool_rejects_blocked_day_without_saving(mocker):
    day = date.today() + timedelta(days=2)
    (summary, changes), save = _exec_plan(
        mocker,
        {
            "set": [
                {
                    "date": day.isoformat(),
                    "workout_type": "Easy Run",
                    "distance": 5,
                    "distance_unit": "km",
                }
            ]
        },
        prefs={"blocked_days": [day.isoformat()]},
    )
    assert summary.startswith("Rejected")
    assert changes == []
    save.assert_not_called()


def test_tool_saves_but_warns_on_overload(mocker):
    # steady_rows() ends at the fixed TODAY, so use dates relative to the real today only for
    # the prefs check above; here the history is stale, so no load exists and nothing warns.
    day = date.today() + timedelta(days=2)
    (summary, changes), save = _exec_plan(
        mocker,
        {
            "set": [
                {
                    "date": day.isoformat(),
                    "workout_type": "Easy Run",
                    "distance": 5,
                    "distance_unit": "km",
                }
            ]
        },
    )
    assert summary.startswith("Created 1 entr") and "[id 101]" in summary
    save.assert_called_once()


def _ops_sent(mocker, args, existing_rows=()):
    """The operations one tool call hands to the calendar, with `existing_rows` in the plan."""
    from types import SimpleNamespace

    from strides_ai.backends.base import BaseBackend

    mocker.patch("strides_ai.backends.base.db.get_all_activities", return_value=steady_rows())
    mocker.patch("strides_ai.backends.base.db.get_training_plan", return_value=list(existing_rows))
    mocker.patch("strides_ai.backends.base.db.get_calendar_prefs", return_value={})
    mocker.patch("strides_ai.backends.base.db.get_unit_system", return_value=UnitSystem.METRIC)
    apply = mocker.patch(
        "strides_ai.backends.base.db.apply_calendar_changes",
        return_value={"created": [900, 901], "updated": [], "deleted": []},
    )
    result = BaseBackend._execute_update_training_plan(
        SimpleNamespace(
            _check_cancelled=lambda: None,
            _budget=SimpleNamespace(tool=lambda a: None, changes=[]),
        ),
        args,
    )
    return result, (apply.call_args.args[0] if apply.called else None)


def test_tool_update_by_id_sends_only_the_given_fields(mocker):
    # An update is a patch: the attached route, notes etc. are never in it, so they survive.
    day = (date.today() + timedelta(days=2)).isoformat()
    existing = [{"id": 5, "kind": "workout", "date": day, "workout_type": "Long Ride"}]
    (summary, _), ops = _ops_sent(mocker, {"set": [{"id": 5, "duration_min": 90}]}, existing)
    assert ops == [{"op": "update", "id": 5, "duration_min": 90}]
    assert "Updated (now) 1 entry" in summary and "[id 5]" in summary


def test_tool_rejects_unknown_entry_id(mocker):
    (summary, changes), ops = _ops_sent(mocker, {"set": [{"id": 999, "duration_min": 90}]})
    assert summary.startswith("Rejected") and changes == [] and ops is None


def test_tool_creates_a_race_and_reports_ids(mocker):
    day = (date.today() + timedelta(days=30)).isoformat()
    args = {
        "set": [
            {
                "date": day,
                "kind": "race",
                "title": "Fall Half",
                "sport": "run",
                "goal_time": "1:45:00",
                "priority": "A",
            }
        ]
    }
    (summary, _), ops = _ops_sent(mocker, args)
    assert ops[0]["goal_time_s"] == 6300 and ops[0]["title"] == "Fall Half"
    assert ops[0]["kind"] == "race" and ops[0]["sport"] == "run"
    assert "[id 900]" in summary


def test_tool_legacy_race_and_rest_types_land_on_the_right_kind(mocker):
    day = (date.today() + timedelta(days=30)).isoformat()
    other = (date.today() + timedelta(days=31)).isoformat()
    args = {
        "set": [
            {"date": day, "workout_type": "Running Race", "description": "10K"},
            {"date": other, "workout_type": "Rest"},
        ]
    }
    _, ops = _ops_sent(mocker, args)
    assert (ops[0]["kind"], ops[0]["sport"], ops[0]["title"]) == ("race", "run", "10K")
    assert ops[1]["kind"] == "rest"


def test_tool_delete_ids_go_first_so_a_replacement_can_reuse_the_day(mocker):
    day = (date.today() + timedelta(days=2)).isoformat()
    existing = [{"id": 5, "kind": "workout", "date": day, "workout_type": "Easy Run"}]
    args = {"delete": [5], "set": [{"date": day, "workout_type": "Easy Run"}]}
    _, ops = _ops_sent(mocker, args, existing)
    assert [o["op"] for o in ops] == ["delete", "create"]


def test_loading_run_spanning_history_into_plan_is_flagged():
    # Three loading actual weeks (each 5%+ above the weeks before it), then a fourth, planned,
    # current week.
    rows, i = [], 1
    monday = TODAY - timedelta(days=TODAY.weekday())
    for w, hours in ((3, 4), (2, 5), (1, 6)):
        # run_row is a 1-hour run; the week's volume is `hours` runs on separate days
        for k in range(hours):
            rows.append(run_row(i, monday - timedelta(weeks=w) + timedelta(days=k), 10))
            i += 1
    rows += [r for r in steady_rows() if r["date"] < (monday - timedelta(weeks=3)).isoformat()]
    plan_rows = [plan(monday + timedelta(days=4), 420.0)]
    current = state(rows=rows, plan_rows=plan_rows).weeks[0]
    assert current["is_current"] and "no_recovery_week" in current["flags"]


def test_tool_validation_is_scoped_to_the_active_mode(mocker):
    from types import SimpleNamespace

    from strides_ai.backends.base import BaseBackend

    ride = {**run_row(1, TODAY - timedelta(days=40), 200.0), "sport_type": "Ride"}
    for name, ret in (
        ("get_all_activities", [ride]),
        ("get_training_plan", [{"id": 12345, "date": "2030-01-01", "kind": "workout"}]),
        ("get_calendar_prefs", {}),
        ("get_unit_system", UnitSystem.METRIC),
    ):
        mocker.patch(f"strides_ai.backends.base.db.{name}", return_value=ret)
    seen = {}
    mocker.patch(
        "strides_ai.training_state.check_plan_changes",
        side_effect=lambda rows, *a: seen.update(rows=rows, mode=a[2]) or [],
    )
    BaseBackend._execute_update_training_plan(
        SimpleNamespace(
            mode="running",
            _check_cancelled=lambda: None,
            _budget=SimpleNamespace(tool=lambda a: None, changes=[]),
        ),
        {"delete": [12345]},
    )
    assert seen["rows"] == [] and seen["mode"] == "running"  # the ride never reaches running load


def test_tool_notes_edit_does_not_rename_a_race(mocker):
    day = (date.today() + timedelta(days=30)).isoformat()
    existing = [
        {"id": 5, "kind": "race", "date": day, "workout_type": "Running Race", "sport": "run"}
    ]
    _, ops = _ops_sent(
        mocker, {"set": [{"id": 5, "description": "Taper week, bring gels"}]}, existing
    )
    assert ops == [{"op": "update", "id": 5, "notes": "Taper week, bring gels"}]


# ── ramp vs recent normal weeks, off weeks, loading runs, capacity, run spikes ──────


def weekly_hours_rows(hours_by_weeks_ago: dict[int, float]) -> list[dict]:
    """One activity per listed past week (Monday), `hours` long. Weeks ago 1 = last week."""
    monday = TODAY - timedelta(days=TODAY.weekday())
    rows = []
    for i, (ago, hours) in enumerate(sorted(hours_by_weeks_ago.items()), start=1):
        d = monday - timedelta(weeks=ago)
        rows.append({**run_row(i, d), "moving_time_s": int(hours * 3600)})
    return rows


def monday_ago(weeks: int) -> date:
    return TODAY - timedelta(days=TODAY.weekday()) - timedelta(weeks=weeks)


def current_week(rows, hours_planned: float, extra_plan=()) -> dict:
    """The current week's state when `hours_planned` is planned on Saturday."""
    saturday = TODAY + timedelta(days=3)
    plan_rows = [plan(saturday, hours_planned * 60), *extra_plan]
    return state(rows=rows, plan_rows=plan_rows).weeks[0]


def series(volumes, **kw):
    start = date(2026, 1, 5)
    return week_series([(start + timedelta(weeks=i), v) for i, v in enumerate(volumes)], **kw)


# The athlete's actual weekly moving hours before the week of 2026-11-16, oldest first: a race
# week (9.2 h), a travel week (0.6 h), a slow return (3.7 h), then 5.7 h. The old rules called the
# next 6.2 h week +22% and three "rising" weeks, and scheduled a down week.
ATHLETE = [4.8, 6.9, 9.0, 3.8, 8.0, 7.9, 4.5, 9.2, 0.6, 3.7, 5.7]


def athlete_state(planned_hours: float):
    ago = {len(ATHLETE) - i: h for i, h in enumerate(ATHLETE)}  # weeks ago, 11 .. 1
    extra = [
        {"date": monday_ago(4).isoformat(), "kind": "race", "workout_type": "Cycling Race"},
        {"date": (monday_ago(3) + timedelta(days=2)).isoformat(), "kind": "travel"},
    ]
    saturday = TODAY + timedelta(days=3)
    return state(
        rows=weekly_hours_rows(ago), plan_rows=[plan(saturday, planned_hours * 60), *extra]
    )


def test_real_weeks_a_travel_dip_is_set_aside_and_the_return_is_not_a_ramp():
    s = athlete_state(6.2)
    week = s.weeks[0]
    assert week["baseline"] == pytest.approx(6.82, abs=0.01)  # mean of 5.7, 9.2, 4.5, 7.9
    assert week["ramp_pct"] == pytest.approx(-9.2, abs=0.1)
    assert week["set_aside"] == [monday_ago(3).isoformat(), monday_ago(2).isoformat()]
    assert week["flags"] == [] and not week["off"]
    assert s.capacity["recent_off_weeks"] == [
        {"week_start": monday_ago(3).isoformat(), "volume": 0.6, "reason": "travel"},
        {"week_start": monday_ago(2).isoformat(), "volume": 3.7, "reason": "low"},
    ]
    assert s.capacity["proven_week"] == {
        "volume": 9.0,
        "weeks": [
            {"week_start": monday_ago(4).isoformat(), "volume": 9.2},
            {"week_start": monday_ago(9).isoformat(), "volume": 9.0},
            {"week_start": monday_ago(7).isoformat(), "volume": 8.0},
        ],
    }
    assert not [c for c in s.conflicts if c["kind"] in ("ramp_high", "no_recovery_week")]


def test_returning_to_the_proven_level_after_a_short_break_is_not_flagged():
    week = athlete_state(8.5).weeks[0]  # +25% vs recent normal weeks: elevated at most
    assert "ramp_high" not in week["flags"]


def test_a_week_holding_a_race_is_never_ramp_flagged():
    vols = [5.0] * 8 + [8.0]
    assert "ramp_high" in series(vols)[-1]["flags"]
    raced = series(vols, race_weeks=frozenset({date(2026, 1, 5) + timedelta(weeks=8)}))
    assert raced[-1]["flags"] == []


def test_a_low_race_week_is_off_as_race_and_counts_as_the_down_week():
    race_week = date(2026, 1, 5) + timedelta(weeks=8)
    out = series([5.0] * 8 + [1.0], race_weeks=frozenset({race_week}))
    assert (out[-1]["off"], out[-1]["off_reason"]) == (True, "race")


@pytest.mark.parametrize(
    "growth, flag", [(1.10, "ramp_elevated"), (1.12, "ramp_high")], ids=["10pct", "12pct"]
)
def test_steady_weekly_growth_reads_about_two_and_a_half_times_against_the_reference(growth, flag):
    out = series([5.0 * growth**k for k in range(12)])
    last = out[-1]
    expected = 100 * (1 / (sum(growth**-k for k in range(1, 5)) / 4) - 1)
    assert last["ramp_pct"] == pytest.approx(expected, abs=0.1)
    assert flag in last["flags"]
    assert ("ramp_high" in last["flags"]) is (flag == "ramp_high")


def test_a_big_percentage_that_is_under_an_hour_is_not_flagged():
    assert series([3.2] * 8 + [4.0])[-1]["flags"] == []  # +25%, +0.8 h
    assert series([2.5] * 8 + [3.3])[-1]["flags"] == []  # +32%, +0.8 h


def test_the_fourth_loading_week_is_flagged_and_steady_weeks_do_not_reset_the_run():
    out = series([5.0] * 6 + [5.5, 5.3, 6.0, 6.5, 5.9, 7.0])
    flagged = [i for i, w in enumerate(out) if "no_recovery_week" in w["flags"]]
    assert flagged == [11]


def test_a_travel_week_is_the_down_week():
    start = date(2026, 1, 5)
    travel = frozenset({start + timedelta(weeks=8)})
    out = series([5.0] * 6 + [5.5, 6.0, 2.0, 6.5, 7.0, 7.5, 8.0], travel_weeks=travel)
    assert (out[8]["off"], out[8]["off_reason"]) == (True, "travel")
    flagged = [i for i, w in enumerate(out) if "no_recovery_week" in w["flags"]]
    assert flagged == [12]  # the run restarts after the travel week; 3 loading weeks pass


def test_a_layoff_is_counted_so_a_return_to_old_volume_is_a_ramp():
    ago = {**{w: 8.0 for w in range(13, 5, -1)}, **{w: 1.0 for w in range(5, 0, -1)}}
    s = state(rows=weekly_hours_rows(ago), plan_rows=[plan(TODAY + timedelta(days=3), 480.0)])
    week = s.weeks[0]
    assert week["baseline"] == pytest.approx(1.0) and "ramp_high" in week["flags"]
    assert week["set_aside"] == []
    assert [w["reason"] for w in s.capacity["recent_off_weeks"]] == ["layoff"] * 5
    assert s.capacity["proven_week"]["volume"] == 8.0  # still shown: what they did before


def test_a_two_week_break_is_set_aside():
    ago = {**{w: 8.0 for w in range(10, 2, -1)}, 2: 1.0, 1: 1.0}
    week = current_week(weekly_hours_rows(ago), 8.0)
    assert week["baseline"] == pytest.approx(8.0) and week["flags"] == []
    assert len(week["set_aside"]) == 2


def test_future_weeks_with_nothing_planned_have_no_ramp():
    weeks = state(rows=weekly_hours_rows({i: 5.0 for i in range(1, 9)})).weeks
    later = [w for w in weeks if not w["is_current"]]
    assert later and all(w["off_reason"] == "unplanned" and w["ramp_pct"] is None for w in later)


def test_under_three_normal_weeks_has_no_ramp_instead_of_a_zero_padded_one():
    rows = weekly_hours_rows({2: 5, 1: 5})
    # Weeks before the first activity are "no data", never zero weeks that would pad a baseline.
    week = state(rows=rows, plan_rows=[plan(TODAY + timedelta(days=3), 360.0)]).weeks[0]
    assert week["ramp_pct"] is None and week["baseline"] is None


def test_short_history_marks_nothing_off_and_has_no_proven_or_typical_week():
    s = state(
        rows=weekly_hours_rows({5: 5, 4: 5, 3: 5, 2: 0.5, 1: 5}),
        plan_rows=[plan(TODAY + timedelta(days=3), 300.0)],
    )
    assert s.capacity["proven_week"] is None and s.typical_week is None
    assert s.capacity["recent_off_weeks"] == []
    assert s.weeks[0]["baseline"] == pytest.approx(3.88)  # 0.5 h counts: too little history


def runs(*specs) -> list[dict]:
    """Runs as (days before TODAY, minutes)."""
    return [
        {**run_row(i, TODAY - timedelta(days=d)), "moving_time_s": int(m * 60)}
        for i, (d, m) in enumerate(specs, start=1)
    ]


def long_run(days_ahead: int, minutes: float) -> dict:
    return plan(TODAY + timedelta(days=days_ahead), minutes, "Long Run")


def test_a_run_more_than_ten_percent_over_the_longest_of_30_days_is_a_spike():
    s = state(rows=runs((10, 55), (20, 40)), plan_rows=[long_run(3, 70)])
    assert s.run_spikes == [
        {
            "date": (TODAY + timedelta(days=3)).isoformat(),
            "hours": pytest.approx(1.17, abs=0.01),
            "longest_hours": pytest.approx(0.92, abs=0.01),
            "longest_date": (TODAY - timedelta(days=10)).isoformat(),
        }
    ]
    assert "run_spike" in {c["kind"] for c in s.conflicts}


def test_run_spike_needs_ten_minutes_and_a_recent_run_and_ignores_cycling_mode():
    assert state(rows=runs((10, 55)), plan_rows=[long_run(3, 64)]).run_spikes == []  # +9 min
    assert state(rows=runs((40, 55)), plan_rows=[long_run(3, 90)]).run_spikes == []
    assert state(rows=runs((10, 55)), plan_rows=[long_run(3, 90)], mode="cycling").run_spikes == []


def test_an_earlier_planned_run_raises_the_reference():
    s = state(rows=runs((10, 55)), plan_rows=[long_run(1, 60), long_run(5, 75)])
    assert [x["longest_hours"] for x in s.run_spikes] == [1.0]  # the planned 60 min, not 55


def test_run_spike_on_a_new_long_run_is_reported_by_check_plan_changes():
    changes = {
        "create": [
            {
                "date": (TODAY + timedelta(days=3)).isoformat(),
                "workout_type": "Long Run",
                "duration_min": 90,
            }
        ]
    }
    out = check_plan_changes(runs((10, 55)), [], {}, "running", UnitSystem.METRIC, TODAY, changes)
    assert [(v.kind, v.hard) for v in out] == [("run_spike", False)]


def test_travel_entries_are_not_listed_as_unscored():
    s = state(plan_rows=[{"date": (TODAY + timedelta(days=2)).isoformat(), "kind": "travel"}])
    assert s.unscored_planned == []


def test_prompt_shows_capacity_one_ramp_and_calls_the_notes_advisory():
    from strides_ai.training_state import render_for_prompt

    text = render_for_prompt(athlete_state(6.2), UnitSystem.IMPERIAL)
    assert "load = logged and planned moving time of all sports" not in text  # running mode
    assert "load = logged and planned moving time of runs only" in text
    assert "Proven weekly level: 9.0 h" in text
    assert "Longest run: last 30 days" in text
    assert "Off weeks set aside from the ramp:" in text and "0.6 h, travel" in text
    assert "-9% vs recent normal weeks (6.8 h)" in text
    assert "screening notes, not injury predictions or limits" in text
    assert "Planning Principles" in text
    assert "BOTH comparisons" not in text and "8-week median" not in text
    assert "mi/day" not in text and "km/day" not in text


def test_a_tiny_rise_is_not_a_loading_week():
    # Running-only volume for a mostly-cycling athlete: +27% and +5% on under an hour are minutes.
    out = series([0.25, 0.5, 0.5, 0.5, 0.75, 1.34, 0.43, 1.92, 0.75, 1.17])
    assert not any("no_recovery_week" in w["flags"] for w in out)


def test_prompt_says_which_sessions_count_in_the_mode():
    from strides_ai.training_state import render_for_prompt

    running = render_for_prompt(state(mode="running"))
    assert "moving time of runs only" in running and "rides are not counted" in running
    assert "moving time of all sports" in render_for_prompt(state(mode="hybrid"))
    assert "rides only" in render_for_prompt(state(mode="cycling"))
