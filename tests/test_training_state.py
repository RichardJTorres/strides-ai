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


def test_big_planned_week_flags_ramp_and_ratio():
    rows = [plan(TODAY + timedelta(days=i), 240.0) for i in range(1, 8)]
    s = state(plan_rows=rows)
    kinds = {c["kind"] for c in s.conflicts}
    assert "ramp_high" in kinds
    assert "ratio_breach" in kinds


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
    assert {v.kind for v in out} >= {"ramp_high", "ratio_breach"}
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


def test_recovery_streak_spanning_history_into_plan_is_flagged():
    # Three rising actual weeks before this one, then a higher planned current week.
    rows, i = [], 1
    monday = TODAY - timedelta(days=TODAY.weekday())
    for w, hours in ((4, 1), (3, 2), (2, 3), (1, 4)):
        # run_row is a 1-hour run; the week's rising volume is `hours` runs on separate days
        for k in range(hours):
            rows.append(run_row(i, monday - timedelta(weeks=w) + timedelta(days=k), 10))
            i += 1
    rows += [r for r in steady_rows() if r["date"] < (monday - timedelta(weeks=5)).isoformat()]
    plan_rows = [plan(monday + timedelta(days=4), 360.0)]
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


# ── ramp baselines: the smaller of the 4-week mean and the 8-week median ────────────


def weekly_hours_rows(hours_by_weeks_ago: dict[int, float]) -> list[dict]:
    """One activity per listed past week (Monday), `hours` long. Weeks ago 1 = last week."""
    monday = TODAY - timedelta(days=TODAY.weekday())
    rows = []
    for i, (ago, hours) in enumerate(sorted(hours_by_weeks_ago.items()), start=1):
        d = monday - timedelta(weeks=ago)
        rows.append({**run_row(i, d), "moving_time_s": int(hours * 3600)})
    return rows


def current_week(rows, hours_planned: float) -> dict:
    """The current week's state when `hours_planned` is planned on Saturday."""
    saturday = TODAY + timedelta(days=3)
    plan_rows = [plan(saturday, hours_planned * 60)]
    return state(rows=rows, plan_rows=plan_rows).weeks[0]


def test_real_sep_nov_weeks_a_travel_dip_does_not_make_a_normal_build_a_danger_ramp():
    # The athlete's actual weekly moving hours before the week of 2026-11-16, oldest first:
    # 9.0, 3.8, 8.0, 7.9, 4.5, 9.2, then travel weeks of 0.6 and 3.7, then 6.5.
    history = [9.0, 3.8, 8.0, 7.9, 4.5, 9.2, 0.6, 3.7, 6.5]
    ago = {len(history) - i: h for i, h in enumerate(history)}  # weeks ago, 9 .. 1
    week = current_week(weekly_hours_rows(ago), 6.75)
    mean4 = (9.2 + 0.6 + 3.7 + 6.5) / 4  # 5.0: the baseline the distance model scolded against
    assert week["baseline_basis"] == "8-week median"
    assert week["baseline"] == pytest.approx(5.5)  # median of 3.8 8.0 7.9 4.5 9.2 0.6 3.7 6.5
    assert week["ramp_pct"] == pytest.approx(22.7, abs=0.1)
    assert week["ramp_pct"] < 100 * (6.75 - mean4) / mean4  # smaller than the 4-week-mean ramp
    assert state(rows=weekly_hours_rows(ago)).typical_week == {
        "median": 5.5,
        "low": 0.6,
        "high": 9.2,
        "weeks": 8,
    }


def test_median_is_not_dragged_down_by_two_deload_weeks():
    ago = {8: 5, 7: 5, 6: 5, 5: 5, 4: 5, 3: 5, 2: 0.5, 1: 0.5}
    week = current_week(weekly_hours_rows(ago), 7.0)
    assert week["baseline_basis"] == "8-week median" and week["baseline"] == pytest.approx(5.0)
    assert week["ramp_pct"] == pytest.approx(40.0)  # the 4-week mean (2.75 h) would say +155%


def test_week_is_flagged_only_when_high_against_both_baselines():
    # The last 4 weeks are the athlete's biggest (mean 8 h, median of 8 is 6.5 h). 10 h is +25%
    # on the mean but +54% on the median; the smaller ramp (the mean's) is the one reported.
    ago = {8: 4, 7: 5, 6: 5, 5: 5, 4: 8, 3: 8, 2: 8, 1: 8}
    week = current_week(weekly_hours_rows(ago), 10.0)
    assert week["baseline_basis"] == "4-week average" and week["ramp_pct"] == pytest.approx(25.0)
    # 9 h: +12.5% on the mean, below the 15% limit, even though it is +38% on the median.
    low = current_week(weekly_hours_rows(ago), 9.0)
    assert low["ramp_pct"] == pytest.approx(12.5) and "ramp_high" not in low["flags"]


def test_short_history_falls_back_to_the_four_week_mean_and_has_no_typical_week():
    ago = {5: 5, 4: 5, 3: 5, 2: 5, 1: 5}  # only five weeks of history: median needs six
    s = state(rows=weekly_hours_rows(ago), plan_rows=[plan(TODAY + timedelta(days=3), 360.0)])
    week = s.weeks[0]
    assert week["baseline_basis"] == "4-week average" and week["ramp_pct"] == pytest.approx(20.0)
    assert s.typical_week is None


def test_under_four_weeks_of_history_has_no_ramp_instead_of_a_zero_padded_one():
    rows = weekly_hours_rows({3: 5, 2: 5, 1: 5})
    # Weeks before the first activity are "no data", never zero weeks that would pad a baseline.
    week = state(rows=rows, plan_rows=[plan(TODAY + timedelta(days=3), 360.0)]).weeks[0]
    assert week["ramp_pct"] is None and week["baseline"] is None


def test_prompt_names_the_baseline_and_the_typical_week_and_calls_the_flags_advisory():
    from strides_ai.training_state import render_for_prompt

    ago = {i: 5.0 for i in range(1, 9)}
    s = state(rows=weekly_hours_rows(ago), plan_rows=[plan(TODAY + timedelta(days=3), 420.0)])
    text = render_for_prompt(s, UnitSystem.IMPERIAL)
    assert "load = moving time" in text and "not an estimate" not in text
    assert "Typical week (the previous 8 completed weeks): median 5.0 h" in text
    assert "vs the 8-week median (5.0 h)" in text
    assert "screening heuristics, not injury predictions" in text
    assert "mi/day" not in text and "km/day" not in text
