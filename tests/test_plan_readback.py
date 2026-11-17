"""update_training_plan tells the coach what is now stored, and refuses guesses."""

from types import SimpleNamespace

import pytest

from strides_ai.backends.base import BaseBackend
from strides_ai.units import UnitSystem

I = UnitSystem.IMPERIAL


def entry(i, d, wtype="Easy Run", km=12.87, minutes=40, intensity="easy", **kw):
    row = {
        "id": i,
        "date": d,
        "kind": "workout",
        "workout_type": wtype,
        "title": None,
        "distance_km": km,
        "elevation_m": None,
        "duration_min": minutes,
        "intensity": intensity,
        "structure_json": None,
        "goal_time_s": None,
        "goal_text": None,
        "priority": None,
    }
    row.update(kw)
    return row


def run(mocker, args, before=(), after=None, applied=None, checks=(), units=I):
    """Execute one update_training_plan call against mocked storage. Returns (summary, apply)."""
    reads = iter([list(before), list(before if after is None else after)])
    mocker.patch(
        "strides_ai.backends.base.db.get_training_plan", side_effect=lambda *a: next(reads)
    )
    mocker.patch("strides_ai.backends.base.db.get_unit_system", return_value=units)
    mocker.patch("strides_ai.backends.base._check_proposed_changes", return_value=list(checks))
    apply = mocker.patch(
        "strides_ai.backends.base.db.apply_calendar_changes",
        return_value=applied or {"created": [], "updated": [], "deleted": []},
    )
    stub = SimpleNamespace(
        _check_cancelled=lambda: None, _budget=SimpleNamespace(tool=lambda a: None, changes=[])
    )
    summary, _ = BaseBackend._execute_update_training_plan(stub, args)
    return summary, apply


def new_run(**extra):
    return {
        "date": "2026-11-21",
        "workout_type": "Easy Run",
        "distance": 8,
        "distance_unit": "mi",
        "duration_min": 40,
        "intensity": "easy",
        **extra,
    }


# ── read-back ─────────────────────────────────────────────────────────────────


def test_a_created_entry_is_read_back_with_weekday_and_the_athletes_units(mocker):
    summary, _ = run(
        mocker,
        {"set": [new_run()]},
        after=[entry(101, "2026-11-21", km=12.87)],
        applied={"created": [101], "updated": [], "deleted": []},
    )
    assert "Created 1 entry:\n  [id 101] Sat 2026-11-21: Easy Run, 8.00 mi, 40 min, easy" in summary
    assert "report them, not what you intended" in summary


def test_an_update_shows_the_values_now_stored_not_the_ones_sent(mocker):
    before = [entry(68, "2026-11-15", "Long Ride", km=51.0, minutes=180)]
    after = [entry(68, "2026-11-15", "Long Ride", km=30.58, minutes=150, intensity="moderate")]
    summary, _ = run(
        mocker,
        {"set": [{"id": 68, "distance": 19, "distance_unit": "mi", "duration_min": 150}]},
        before=before,
        after=after,
        applied={"created": [], "updated": [68], "deleted": []},
    )
    assert (
        "Updated (now) 1 entry:\n  [id 68] Sun 2026-11-15: Long Ride, 19.00 mi, 150 min, moderate"
        in summary
    )


def test_a_removed_entry_is_described_so_a_wrong_delete_is_visible(mocker):
    before = [entry(71, "2026-11-19", "Easy Ride", km=14.48)]
    summary, _ = run(
        mocker,
        {"delete": [71]},
        before=before,
        after=[],
        applied={"created": [], "updated": [], "deleted": [71]},
    )
    assert (
        "Removed 1 entry:\n  [id 71] Thu 2026-11-19: Easy Ride, 9.00 mi, 40 min, easy (deleted)"
        in summary
    )


def test_race_read_back_names_the_race_goal_and_priority(mocker):
    race = entry(
        88,
        "2026-12-12",
        "Running Race",
        km=94.9,
        minutes=None,
        intensity=None,
        kind="race",
        title="Evergreen Grinder",
        goal_time_s=32400,
        priority="A",
    )
    summary, _ = run(
        mocker,
        {"set": [{"date": "2026-12-12", "kind": "race", "title": "Evergreen Grinder"}]},
        after=[race],
        applied={"created": [88], "updated": [], "deleted": []},
    )
    assert (
        "[id 88] Sat 2026-12-12: Evergreen Grinder (Running Race), 58.97 mi, goal 9:00:00, priority A"
        in summary
    )


def test_a_failed_read_back_never_hides_a_completed_write(mocker):
    mocker.patch("strides_ai.backends.base.db.get_unit_system", return_value=I)
    mocker.patch("strides_ai.backends.base._check_proposed_changes", return_value=[])
    mocker.patch(
        "strides_ai.backends.base.db.get_training_plan",
        side_effect=[[], RuntimeError("db went away")],
    )
    mocker.patch(
        "strides_ai.backends.base.db.apply_calendar_changes",
        return_value={"created": [101], "updated": [], "deleted": []},
    )
    stub = SimpleNamespace(
        _check_cancelled=lambda: None, _budget=SimpleNamespace(tool=lambda a: None, changes=[])
    )
    summary, changes = BaseBackend._execute_update_training_plan(stub, {"set": [new_run()]})
    assert summary.startswith("Created 1 entry:\n  [id 101] Sat 2026-11-21: Easy Run")
    assert "report them" not in summary and changes[0]["id"] == 101


def test_a_structured_workout_the_calendar_did_not_keep_is_called_out(mocker):
    structure = {"blocks": [{"type": "steady", "minutes": 20, "intensity": 0.7}]}
    summary, _ = run(
        mocker,
        {"set": [new_run(workout_type="Easy Ride", structure=structure)]},
        after=[entry(101, "2026-11-21", "Easy Ride")],  # stored without structure_json
        applied={"created": [101], "updated": [], "deleted": []},
    )
    assert "Not saved: the structured workout on [id 101]" in summary


# ── refusals instead of guesses ───────────────────────────────────────────────


@pytest.mark.parametrize(
    "item, fragment",
    [
        ({"distance": 8}, "`distance` needs `distance_unit` (km or mi)"),
        (
            {"distance": 8, "distance_unit": "miles"},
            "`distance_unit` must be km or mi, got 'miles'",
        ),
        ({"elevation": 1200}, "`elevation` needs `elevation_unit` (m or ft)"),
        ({"distance": "ten miles", "distance_unit": "mi"}, "`distance` must be a number"),
    ],
)
def test_measurements_without_a_valid_unit_are_refused_not_assumed_to_be_km(mocker, item, fragment):
    summary, apply = run(
        mocker, {"set": [{"date": "2026-11-21", "workout_type": "Easy Run", **item}]}
    )
    assert summary.startswith("Rejected, no changes made.") and fragment in summary
    assert summary.count("Item 1:") == 1
    apply.assert_not_called()


def test_the_legacy_km_fields_still_work_without_a_unit(mocker):
    summary, apply = run(
        mocker,
        {"set": [{"date": "2026-11-21", "workout_type": "Easy Run", "distance_km": 8}]},
        after=[entry(101, "2026-11-21", km=8)],
        applied={"created": [101], "updated": [], "deleted": []},
    )
    assert summary.startswith("Created 1 entry") and apply.called


def test_deleting_an_id_that_does_not_exist_is_an_error_not_a_phantom_removal(mocker):
    summary, apply = run(mocker, {"delete": [999]}, before=[entry(5, "2026-11-20")])
    assert summary == "Rejected, no changes made. No calendar entry with id 999 to delete"
    apply.assert_not_called()


def test_an_item_that_is_not_an_object_is_refused_not_a_crash(mocker):
    summary, apply = run(mocker, {"set": ["2026-11-21 easy run"]})
    assert summary == "Rejected, no changes made. Item 1 of `set` is not an object"
    apply.assert_not_called()


# ── guardrails that cannot run say so ─────────────────────────────────────────


def test_a_guardrail_failure_is_reported_instead_of_passing_silently(mocker):
    from strides_ai.backends import base

    mocker.patch("strides_ai.training_state.check_plan_changes", side_effect=RuntimeError("boom"))
    mocker.patch("strides_ai.backends.base.db.get_all_activities", return_value=[])
    mocker.patch("strides_ai.backends.base.db.get_calendar_prefs", return_value={})
    mocker.patch("strides_ai.backends.base.db.get_unit_system", return_value=I)
    mocker.patch("strides_ai.backends.base.db.get_training_plan", return_value=[])
    violations = base._check_proposed_changes({"create": [], "update": [], "delete": []}, "running")
    assert [v.kind for v in violations] == [base.GUARDRAIL_UNAVAILABLE]
    assert violations[0].hard is False

    summary, apply = run(
        mocker,
        {"set": [new_run()]},
        after=[entry(101, "2026-11-21")],
        applied={"created": [101], "updated": [], "deleted": []},
        checks=violations,
    )
    assert apply.called  # an unavailable check never blocks the edit...
    assert "Not checked: The ramp, fatigue and blocked-day checks could not run" in summary
    assert "Consider revising" not in summary  # ...and is not dressed up as a plan problem


# ── a tool that raises does not end the turn ──────────────────────────────────


def _backend_stub(run_tool):
    return SimpleNamespace(
        _budget=SimpleNamespace(tools=0),
        limits=SimpleNamespace(tools=16),
        _run_tool=run_tool,
    )


def test_a_tool_that_raises_returns_an_error_the_model_can_act_on():
    def boom(*a):
        raise TypeError("bad shape")

    out = BaseBackend._run_call(_backend_stub(boom), "update_training_plan", {}, [], [])
    assert out.startswith("Error: update_training_plan failed (TypeError)")
    assert "get_calendar" in out  # it cannot promise nothing changed


def test_cancellation_and_budget_stops_still_propagate():
    from strides_ai.budget import BudgetExceeded

    for exc in (InterruptedError("client left"), BudgetExceeded("deadline")):

        def stop(*a, exc=exc):
            raise exc

        with pytest.raises(type(exc)):
            BaseBackend._run_call(_backend_stub(stop), "update_training_plan", {}, [], [])


# ── memories ──────────────────────────────────────────────────────────────────


def test_a_duplicate_or_failed_memory_is_not_reported_to_the_athlete_as_saved():
    from strides_ai.db.memories import DUPLICATE_RESULT

    for result, shown in (
        ("Memory saved.", True),
        ("Memory updated.", True),
        (DUPLICATE_RESULT, False),
        ("Error: x", False),
    ):
        saved = []
        stub = SimpleNamespace(
            _execute_save_memory=lambda args, result=result: (result, "goal", "x"),
        )
        BaseBackend._run_tool(stub, "save_memory", {}, saved, [])
        assert bool(saved) is shown, result
