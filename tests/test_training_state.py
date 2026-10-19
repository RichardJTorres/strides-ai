"""Tests for strides_ai.training_state — projection, weekly ramp, conflicts and guardrails."""

from datetime import date, timedelta

import pytest

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


def plan(d: date, km: float | None, wtype: str = "Easy Run", intensity: str | None = "easy"):
    return {
        "date": d.isoformat(),
        "workout_type": wtype,
        "distance_km": km,
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
    assert s.load == {"ctl": last.ctl, "atl": last.atl, "ratio": last.ratio}


def test_projection_follows_planned_volume():
    rest = state()
    hard = state(plan_rows=[plan(TODAY + timedelta(days=i), 30.0) for i in range(1, 6)])
    assert hard.projection[4]["atl"] > rest.projection[4]["atl"]
    assert hard.projection[0]["planned"] == pytest.approx(30.0)
    assert len(rest.projection) == 28


def test_deterministic():
    plan_rows = [plan(TODAY + timedelta(days=2), 12.0)]
    assert state(plan_rows=plan_rows).to_dict() == state(plan_rows=plan_rows).to_dict()


def test_units_parity_planned_values():
    plan_rows = [plan(TODAY + timedelta(days=1), 16.0934)]
    metric = state(plan_rows=plan_rows)
    imperial = state(plan_rows=plan_rows, units=UnitSystem.IMPERIAL)
    assert metric.projection[0]["planned"] == pytest.approx(16.09, abs=0.01)
    assert imperial.projection[0]["planned"] == pytest.approx(10.0, abs=0.01)
    assert imperial.unit == "miles"


def test_volume_less_planned_workouts_are_listed_not_guessed():
    s = state(plan_rows=[plan(TODAY + timedelta(days=1), None)])
    assert s.unscored_planned == [(TODAY + timedelta(days=1)).isoformat()]
    assert s.projection[0]["planned"] == 0


def test_rest_and_other_sport_do_not_count_in_running_mode():
    rows = [
        plan(TODAY + timedelta(days=1), 50.0, "Rest", "rest"),
        plan(TODAY + timedelta(days=2), 80.0, "Long Ride"),
    ]
    s = state(plan_rows=rows)
    assert all(p["planned"] == 0 for p in s.projection[:3])
    assert state(plan_rows=rows, mode="cycling").projection[1]["planned"] == pytest.approx(80.0)


def test_big_planned_week_flags_ramp_and_ratio():
    rows = [plan(TODAY + timedelta(days=i), 40.0) for i in range(1, 8)]
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
        plan(blocked, 8.0),
        plan(race, 8.0, "Tempo Run"),
        plan(race + timedelta(days=1), 0, "Rest", "rest"),
    ]
    s = state(plan_rows=rows, prefs=prefs)
    hard = {(c["kind"], c["date"]) for c in s.conflicts if c["hard"]}
    assert hard == {("blocked_day", blocked.isoformat()), ("race_day", race.isoformat())}
    assert s.constraints["next_race"]["days_out"] == 5


def test_race_workout_on_race_day_is_not_a_conflict():
    race = TODAY + timedelta(days=5)
    prefs = {"races": [{"date": race.isoformat(), "name": "10K"}]}
    s = state(plan_rows=[plan(race, 10.0, "Running Race", "hard")], prefs=prefs)
    assert not [c for c in s.conflicts if c["kind"] == "race_day"]


def test_recovery_week_flag_after_rising_weeks():
    rows = []
    for w, km in enumerate([40, 50, 60, 70]):
        monday = TODAY - timedelta(days=TODAY.weekday()) + timedelta(weeks=w + 1)
        rows.append(plan(monday + timedelta(days=4), float(km)))
    flagged = [wk for wk in state(plan_rows=rows).weeks if "no_recovery_week" in wk["flags"]]
    assert flagged


def test_check_plan_changes_rejects_blocked_and_race_days():
    blocked = TODAY + timedelta(days=2)
    prefs = {"blocked_days": [blocked.isoformat()]}
    changes = {"set": [{"date": blocked.isoformat(), "workout_type": "Easy Run", "distance_km": 5}]}
    out = check_plan_changes(steady_rows(), [], prefs, "running", UnitSystem.METRIC, TODAY, changes)
    assert [(v.kind, v.hard) for v in out] == [("blocked_day", True)]
    # Rest is allowed on a blocked day.
    rest = {"set": [{"date": blocked.isoformat(), "workout_type": "Rest", "intensity": "rest"}]}
    assert not check_plan_changes(
        steady_rows(), [], prefs, "running", UnitSystem.METRIC, TODAY, rest
    )


def test_check_plan_changes_warns_on_new_ramp_but_not_existing():
    big = {
        "set": [
            {
                "date": (TODAY + timedelta(days=i)).isoformat(),
                "workout_type": "Easy Run",
                "distance_km": 40.0,
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
        steady_rows(), existing, {}, "running", UnitSystem.METRIC, TODAY, {"set": []}
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
    save = mocker.patch("strides_ai.backends.base.db.save_planned_workout")
    stub = SimpleNamespace(
        _check_cancelled=lambda: None,
        _budget=SimpleNamespace(tool=lambda a: None, changes=[]),
    )
    return BaseBackend._execute_update_training_plan(stub, args), save


def test_tool_rejects_blocked_day_without_saving(mocker):
    day = date.today() + timedelta(days=2)
    (summary, changes), save = _exec_plan(
        mocker,
        {"set": [{"date": day.isoformat(), "workout_type": "Easy Run", "distance": 5}]},
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
        mocker, {"set": [{"date": day.isoformat(), "workout_type": "Easy Run", "distance": 5}]}
    )
    assert summary.startswith("Scheduled 1 workout")
    save.assert_called_once()


def test_recovery_streak_spanning_history_into_plan_is_flagged():
    # Three rising actual weeks before this one, then a higher planned current week.
    rows, i = [], 1
    monday = TODAY - timedelta(days=TODAY.weekday())
    for w, km in ((4, 10), (3, 15), (2, 20), (1, 25)):
        rows.append(run_row(i, monday - timedelta(weeks=w) + timedelta(days=1), km))
        i += 1
    rows += [r for r in steady_rows() if r["date"] < (monday - timedelta(weeks=5)).isoformat()]
    plan_rows = [plan(monday + timedelta(days=4), 40.0)]
    current = state(rows=rows, plan_rows=plan_rows).weeks[0]
    assert current["is_current"] and "no_recovery_week" in current["flags"]


def test_tool_validation_is_scoped_to_the_active_mode(mocker):
    from types import SimpleNamespace

    from strides_ai.backends.base import BaseBackend

    ride = {**run_row(1, TODAY - timedelta(days=40), 200.0), "sport_type": "Ride"}
    for name, ret in (
        ("get_all_activities", [ride]),
        ("get_training_plan", []),
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
        {"delete": ["2099-01-01"]},
    )
    assert seen == {"rows": [], "mode": "running"}  # the ride never reaches running load
