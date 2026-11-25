"""The generate-plan guardrails must actually check the generated block (they once passed a change
shape ``training_state.apply_changes`` ignores, so nothing was ever dropped or warned about)."""

from datetime import timedelta

import pytest

from strides_ai.api.routers.calendar import _apply_guardrails
from strides_ai.training_state import apply_changes
from strides_ai.units import UnitSystem
from tests.test_training_state import TODAY, steady_rows


def _workout(d, minutes=60.0, wtype="Easy Run"):
    return {
        "date": d.isoformat(),
        "workout_type": wtype,
        "distance_km": None,
        "duration_min": minutes,
        "intensity": "easy",
    }


def _guard(workouts, plan_rows=(), prefs=None, start=None, end=None):
    start = start or (TODAY + timedelta(days=1)).isoformat()
    end = end or (TODAY + timedelta(days=7)).isoformat()
    return _apply_guardrails(
        {"workouts": list(workouts), "summary": ""},
        steady_rows(),
        list(plan_rows),
        prefs or {},
        "running",
        UnitSystem.METRIC,
        TODAY,
        start,
        end,
    )


def test_apply_changes_rejects_an_unknown_change_shape():
    with pytest.raises(ValueError, match="set"):
        apply_changes([], {"set": [_workout(TODAY + timedelta(days=1))]})


def test_generated_workout_on_a_blocked_day_is_dropped_with_a_warning():
    blocked = TODAY + timedelta(days=2)
    kept = _workout(TODAY + timedelta(days=1))
    out = _guard([kept, _workout(blocked)], prefs={"blocked_days": [blocked.isoformat()]})
    assert [w["date"] for w in out["workouts"]] == [kept["date"]]
    assert any(w.startswith(f"Removed {blocked.isoformat()}") for w in out["warnings"])


def test_generated_rest_on_a_blocked_day_is_kept():
    blocked = TODAY + timedelta(days=2)
    rest = {**_workout(blocked, minutes=None, wtype="Rest"), "intensity": "rest"}
    out = _guard([rest], prefs={"blocked_days": [blocked.isoformat()]})
    assert out["workouts"] == [rest]
    assert out["warnings"] == []


def test_a_heavy_generated_block_is_flagged_without_dropping_it():
    block = [_workout(TODAY + timedelta(days=i), 240.0) for i in range(1, 8)]
    out = _guard(block)
    assert len(out["workouts"]) == 7
    assert any("screening line" in w for w in out["warnings"])  # advisory ramp note


def test_replace_removes_only_the_workouts_in_the_range_from_the_checked_plan(mocker):
    """Replace (the modal's default) deletes the existing *workout* entries in the range as the
    generated ones are added, so the check must not count them twice. Races, rest days and
    entries outside the range stay."""
    check = mocker.patch("strides_ai.api.routers.calendar.check_plan_changes", return_value=[])
    day = lambda n: (TODAY + timedelta(days=n)).isoformat()  # noqa: E731
    plan_rows = [
        {"id": 1, "kind": "workout", "date": day(1), "workout_type": "Easy Run"},
        {"id": 2, "kind": "workout", "date": day(7), "workout_type": "Long Run"},
        {"id": 3, "kind": "race", "date": day(3), "workout_type": "Running Race"},
        {"id": 4, "kind": "rest", "date": day(4), "workout_type": "Rest"},
        {"id": 5, "kind": "workout", "date": day(8), "workout_type": "Easy Run"},  # after range
        {"id": 6, "kind": "workout", "date": day(0), "workout_type": "Easy Run"},  # before range
    ]
    generated = [_workout(TODAY + timedelta(days=2))]
    _guard(generated, plan_rows=plan_rows, start=day(1), end=day(7))
    changes = check.call_args.args[-1]
    assert set(changes) == {"create", "delete"}
    assert changes["create"] == generated
    assert sorted(changes["delete"]) == [1, 2]
