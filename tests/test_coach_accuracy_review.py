"""Regression coverage for load previews and the evidence exposed to the coach."""

from datetime import date, timedelta

import pytest

from strides_ai import db
from strides_ai.backends.base import _plan_ops
from strides_ai.coach import entry_summary
from strides_ai.insights import build_digest, build_insights_prompt
from strides_ai.lookup_tools import calendar_range
from strides_ai.training_state import (
    apply_changes,
    build_training_state,
    check_plan_changes,
    render_for_prompt,
)
from strides_ai.units import UnitSystem

TODAY = date(2026, 11, 16)
UNITS = UnitSystem.METRIC
STRUCTURE = {"blocks": [{"kind": "steady", "duration_s": 14400, "pct": 0.7}]}


def history():
    return [
        {
            "date": (TODAY - timedelta(days=i)).isoformat(),
            "moving_time_s": 1800,
            "sport_type": "Ride",
        }
        for i in range(1, 85)
    ]


def state(plan):
    return build_training_state(history(), plan, {}, "cycling", UNITS, TODAY)


@pytest.mark.parametrize(
    "patch",
    [
        {"structure": STRUCTURE},
        {"structure": STRUCTURE, "duration_min": 10},
        {"duration_min": 10},  # retained structure still overrides a duration-only edit
        {"structure": None, "duration_min": 30},
        {"structure": {"blocks": []}, "duration_min": 30},
        {"workout_type": "Easy Run", "structure": STRUCTURE, "duration_min": 30},
    ],
)
def test_structure_update_preview_matches_real_storage(tmp_db, patch):
    db.apply_calendar_changes(
        [
            {
                "op": "create",
                "kind": "workout",
                "date": "2026-11-17",
                "workout_type": "Indoor Ride",
                "structure": STRUCTURE,
            }
        ]
    )
    before = db.get_training_plan()
    ops, proposed, errors = _plan_ops({"set": [{"id": before[0]["id"], **patch}]}, before)
    assert not errors
    preview = apply_changes(before, proposed)
    db.apply_calendar_changes(ops)
    stored = db.get_training_plan()
    assert preview[0]["duration_min"] == stored[0]["duration_min"]
    assert preview[0]["structure_json"] == stored[0]["structure_json"]
    assert state(preview).weeks == state(stored).weeks
    assert state(preview).projection == state(stored).projection


def test_structure_only_create_warns_before_write_and_matches_storage(tmp_db):
    ops, proposed, errors = _plan_ops(
        {"set": [{"date": "2026-11-17", "workout_type": "Indoor Ride", "structure": STRUCTURE}]}, []
    )
    assert not errors
    warnings = check_plan_changes(history(), [], {}, "cycling", UNITS, TODAY, proposed)
    assert warnings == []  # a 4 h structured ride on a 3.5 h week is inside screening
    assert state(apply_changes([], proposed)).weeks[0]["ramp_pct"] == pytest.approx(14.3)
    preview = apply_changes([], proposed)
    db.apply_calendar_changes(ops)
    assert state(preview).projection == state(db.get_training_plan()).projection
    assert state(preview).weeks[0]["volume"] == 4.0


@pytest.mark.parametrize(
    "kind,wtype", [("workout", "Easy Run"), ("travel", "Travel"), ("race", "Running Race")]
)
def test_lookup_and_receipt_include_bounded_instructions(kind, wtype):
    row = {
        "id": 1,
        "kind": kind,
        "date": "2026-11-17",
        "workout_type": wtype,
        "objective": "Practice fueling" if kind == "workout" else None,
        "notes": "Pacing instruction " + "x" * 1000,
    }
    lookup = calendar_range(lambda a, b: [row], {}, UNITS, TODAY)
    receipt = entry_summary(row)
    for text in (lookup, receipt):
        assert "Pacing instruction" in text
        assert "x" * 161 not in text
        if kind == "workout":
            assert "Practice fueling" in text


def ramp_history(end):
    # Historical median is 10 h; the last four weeks average 6 h.
    return [
        {
            "date": (end - timedelta(weeks=8 - i)).isoformat(),
            "moving_time_s": h * 3600,
            "sport_type": "Run",
        }
        for i, h in enumerate([10, 10, 10, 10, 10, 10, 2, 2])
    ]


def test_a_two_week_dip_is_set_aside_and_named_so_the_coach_can_judge_it():
    # Two low weeks are a short break (travel, a cold): the return to 10 h is measured against the
    # normal weeks, and the prompt names the set-aside weeks so the coach can ask why they were low.
    rows = ramp_history(TODAY)
    planned = [{"date": "2026-11-17", "workout_type": "Long Run", "duration_min": 600}]
    result = build_training_state(rows, planned, {}, "running", UNITS, TODAY)
    week = result.weeks[0]
    assert week["ramp_pct"] == 0 and week["baseline"] == 10.0
    assert week["set_aside"] == ["2026-11-02", "2026-11-09"]
    prompt = render_for_prompt(result)
    assert (
        "Off weeks set aside from the ramp: 2026-11-02 (2.0 h, low), 2026-11-09 (2.0 h, low)"
        in (prompt)
    )
    assert "rebuild gradually" not in prompt  # that judgement belongs to the principles


def test_insights_uses_the_same_ramp_rule_as_the_coach():
    last_week = TODAY - timedelta(weeks=1)
    rows = ramp_history(last_week) + [
        {"date": last_week.isoformat(), "moving_time_s": 36000, "sport_type": "Run"}
    ]
    rows = [{"id": i, **row} for i, row in enumerate(rows)]
    digest = build_digest(rows, "running", UNITS, TODAY)
    ramp = next(m for m in digest["metrics"] if m["id"] == "volume.ramp")
    assert (ramp["baseline"], ramp["delta_pct"], ramp["flags"]) == (10.0, 0.0, [])
    prompt = build_insights_prompt(digest)
    assert "8-week median" not in prompt and "4-week average" not in prompt


def test_decoupling_readouts_do_not_infer_fitness_from_passing_filters():
    from strides_ai.analysis import build_analysis_summary, build_precomputed_brief
    from strides_ai.coach import _analysis_guide_section
    from strides_ai.modes import MODES

    row = {
        "sport_type": "Run",
        "moving_time_s": 3600,
        "distance_m": 10000,
        "elevation_gain_m": 0,
        "cardiac_decoupling_pct": 12.0,
        "analysis_summary": "done",
    }
    summary = build_analysis_summary(row)
    assert "interpret only for steady aerobic efforts" in summary
    guide = _analysis_guide_section(MODES["running"], [row])
    assert "does not establish a steady aerobic effort" in guide
    streams = {
        "time": list(range(120)),
        "heartrate": [140] * 60 + [160] * 60,
        "velocity_smooth": [3.0] * 120,
    }
    brief = build_precomputed_brief(streams, row)
    assert "confirm a steady aerobic effort" in brief
    assert "significant fatigue" not in brief and "good aerobic efficiency" not in brief
