"""The what-if digest: a deterministic before/after diff of a hypothetical calendar change.

Fixtures are the ones tests/test_training_state.py uses: a steady history of one-hour runs every
second day ending on Wednesday 2026-06-03, so the previous weeks alternate between 4 and 3 hours
(4-week mean = 8-week median = 3.5 h) and the current week holds 2 h (Mon and Wed)."""

import json
from datetime import timedelta

import pytest

from strides_ai.backends.base import _plan_ops
from strides_ai.training_state import changes_from_ops
from strides_ai.units import UnitSystem
from strides_ai.what_if import (
    MAX_REASONS,
    build_what_if_digest,
    build_what_if_prompt,
    parse_what_if_response,
    verdict_floor,
)
from tests.test_coach_accuracy_review import STRUCTURE
from tests.test_training_state import TODAY, run_row, steady_rows

FRIDAY = TODAY + timedelta(days=2)
WEEK = "2026-06-01"


def create(d=FRIDAY, wtype="Strength", minutes=45, **extra):
    return {
        "op": "create",
        "kind": "workout",
        "date": d.isoformat(),
        "workout_type": wtype,
        "duration_min": minutes,
        "intensity": "moderate",
        **extra,
    }


def entry(entry_id, d, wtype="Easy Run", minutes=60, **extra):
    return {
        "id": entry_id,
        "kind": "workout",
        "date": d.isoformat(),
        "workout_type": wtype,
        "duration_min": minutes,
        "distance_km": None,
        "intensity": "easy",
        **extra,
    }


def digest(ops, plan_rows=(), rows=None, prefs=None, mode="running", units=UnitSystem.METRIC):
    return build_what_if_digest(
        steady_rows() if rows is None else rows,
        list(plan_rows),
        prefs or {},
        mode,
        units,
        TODAY,
        ops,
    )


def metric(d, metric_id):
    return next((m for m in d["metrics"] if m["id"] == metric_id), None)


# ── the numbers ──────────────────────────────────────────────────────────────────


def test_a_friday_strength_session_adds_its_hours_to_the_week():
    d = digest([create()])
    volume = metric(d, f"week.{WEEK}.volume")
    # Mon 1 h + Wed 1 h logged, plus 45 min planned: 2 -> 2.75 h.
    assert (volume["before"], volume["after"], volume["delta"]) == (2.0, 2.75, 0.75)
    assert volume["formatted_delta"] == "+0.75 h"
    # Against a 3.5 h baseline: (2 - 3.5) / 3.5 = -42.9 %, (2.75 - 3.5) / 3.5 = -21.4 %.
    ramp = metric(d, f"week.{WEEK}.ramp")
    assert (ramp["before"], ramp["after"]) == (-42.9, -21.4)
    assert d["context"]["typical_week"]["median"] == 3.5
    assert d["sufficient"] and d["missing"] == [] and d["unit"] == "h"


def test_the_digest_agrees_with_the_training_state_it_is_built_from():
    from strides_ai.training_state import apply_changes, build_training_state

    d = digest([create()])
    after = build_training_state(
        steady_rows(),
        apply_changes([], changes_from_ops([create()], [])),
        {},
        "running",
        UnitSystem.METRIC,
        TODAY,
    )
    assert metric(d, f"week.{WEEK}.volume")["after"] == after.weeks[0]["volume"]
    peak = max((p for p in after.projection), key=lambda p: p["ratio"])
    ratio = metric(d, "load.peak_ratio")
    assert (ratio["after"], ratio["dates"]["after"]) == (peak["ratio"], peak["date"])


def test_a_later_week_ramp_moves_when_its_reference_does():
    """Adding 10 h in the week of Jun 8 changes the reference of the week of Jun 15, which holds a
    1 h run of its own, so its ramp moves although its own volume did not."""
    plan = [entry(1, TODAY + timedelta(days=13))]  # Tue 2026-06-16, 1 h
    d = digest([create(TODAY + timedelta(days=9), "Easy Run", 600)], plan)
    assert metric(d, "week.2026-06-08.volume")["delta"] == 10.0
    assert metric(d, "week.2026-06-15.volume") is None  # its own volume did not change
    # Jun 1 (2 h, under 60% of the 3.5 h median) is an off week and Jun 8 has nothing planned, so
    # both are set aside: the reference is May 25 3, May 18 4, May 11 3, May 4 4 = 3.5 h. With
    # Jun 8 at 10 h it is Jun 8 10, May 25 3, May 18 4, May 11 3 = 5 h.
    ramp = metric(d, "week.2026-06-15.ramp")
    assert (ramp["before"], ramp["after"]) == (-71.4, -80.0)  # (1-3.5)/3.5, (1-5)/5


def test_a_change_that_moves_nothing_reports_no_metrics():
    assert digest([create(TODAY - timedelta(days=3))])["metrics"] == []


# ── digest is deterministic and unit-neutral ───────────────────────────────────────


def test_same_inputs_give_a_byte_identical_digest():
    a = json.dumps(digest([create()]), sort_keys=True)
    b = json.dumps(digest([create()]), sort_keys=True)
    assert a == b


def test_load_numbers_do_not_depend_on_the_unit_system():
    ops = [create(wtype="Easy Run", minutes=40, distance_km=8.0)]
    metric_d = digest(ops, units=UnitSystem.METRIC)
    imperial_d = digest(ops, units=UnitSystem.IMPERIAL)
    assert metric_d["metrics"] == imperial_d["metrics"]
    assert [c["hours"] for c in metric_d["changes"]] == [c["hours"] for c in imperial_d["changes"]]
    assert "8.00 km" in metric_d["changes"][0]["label"]
    assert "4.97 mi" in imperial_d["changes"][0]["label"]


# ── entries the load model ignores say why ─────────────────────────────────────────


@pytest.mark.parametrize(
    "op,reason",
    [
        (create(TODAY - timedelta(days=2)), "past"),
        (create(TODAY + timedelta(days=40)), "beyond_horizon"),
        (create(wtype="Yoga"), "not_in_load"),
        (create(minutes=None), "no_duration"),
        (create(wtype="Easy Ride"), "not_in_load"),  # another sport's workout in running mode
    ],
)
def test_an_entry_the_load_model_ignores_carries_its_reason(op, reason):
    change = digest([op])["changes"][0]
    assert change["counted"] is False and change["reason"] == reason
    assert metric(digest([op]), f"week.{WEEK}.volume") is None


def test_an_entry_that_counts_has_no_reason_and_is_scored():
    change = digest([create()])["changes"][0]
    assert (change["counted"], change["reason"], change["scored"]) == (True, None, True)
    assert change["hours"] == 0.75 and change["label"] == "Strength, 45 min"
    assert digest([create(wtype="Yoga")])["changes"][0]["scored"] is False


def test_the_same_ride_counts_in_cycling_mode():
    change = digest([create(wtype="Easy Ride")], mode="cycling")["changes"][0]
    assert change["counted"] is True


# ── updates, deletes and neighbours ────────────────────────────────────────────────


def test_shortening_a_planned_run_lowers_the_week():
    plan = [entry(7, FRIDAY, "Easy Run", 90)]
    d = digest([{"op": "update", "id": 7, "duration_min": 30}], plan)
    assert metric(d, f"week.{WEEK}.volume")["delta"] == -1.0
    change = d["changes"][0]
    assert (change["op"], change["entry_id"], change["hours"]) == ("update", 7, 0.5)
    assert [n["modified"] for n in d["context"]["neighbors"] if n["id"] == 7] == [True]


def test_deleting_a_planned_run_removes_its_hours():
    plan = [entry(7, FRIDAY, "Easy Run", 90)]
    d = digest([{"op": "delete", "id": 7}], plan)
    assert metric(d, f"week.{WEEK}.volume")["delta"] == -1.5
    assert d["changes"][0]["op"] == "delete" and d["changes"][0]["entry_id"] == 7
    assert all(n["id"] != 7 for n in d["context"]["neighbors"])  # gone after the change


def test_neighbours_are_the_entries_within_three_days_of_the_change():
    plan = [
        entry(1, FRIDAY - timedelta(days=3)),  # Tue: in
        entry(2, FRIDAY + timedelta(days=3)),  # Mon: in
        entry(3, FRIDAY + timedelta(days=4)),  # out
        entry(4, FRIDAY - timedelta(days=4)),  # out
    ]
    neighbors = digest([create()], plan)["context"]["neighbors"]
    assert [(n["id"], n["hypothetical"]) for n in neighbors] == [
        (1, False),
        (None, True),
        (2, False),
    ]
    assert neighbors[1]["day"] == "Fri 2026-06-05" and neighbors[1]["type"] == "Strength"


# ── guardrails ────────────────────────────────────────────────────────────────────


def test_a_workout_on_a_blocked_day_is_a_new_hard_violation():
    d = digest([create()], prefs={"blocked_days": [FRIDAY.isoformat()]})
    kinds = [(v["kind"], v["hard"]) for v in d["violations"]["new"]]
    assert kinds == [("blocked_day", True)]
    assert d["context"]["blocked_days"] == [FRIDAY.isoformat()]


def test_a_workout_on_race_day_is_a_new_hard_violation():
    prefs = {"races": [{"date": FRIDAY.isoformat(), "name": "10K"}]}
    d = digest([create(minutes=90)], prefs=prefs)
    assert ("race_day", True) in [(v["kind"], v["hard"]) for v in d["violations"]["new"]]
    assert d["context"]["next_race"]["days_out"] == 2


def test_removing_the_workout_on_a_blocked_day_resolves_the_conflict():
    plan = [entry(5, FRIDAY)]
    prefs = {"blocked_days": [FRIDAY.isoformat()]}
    d = digest([{"op": "delete", "id": 5}], plan, prefs=prefs)
    assert [v["kind"] for v in d["violations"]["resolved"]] == ["blocked_day"]
    assert d["violations"]["new"] == []


def test_a_heavy_block_raises_the_peak_ratio_and_flags_the_ramp_not_the_ratio():
    block = [create(TODAY + timedelta(days=i), "Easy Run", 240) for i in range(1, 8)]
    d = digest(block)
    ratio = metric(d, "load.peak_ratio")
    assert ratio["after"] > d["thresholds"]["acwr_high"] > ratio["before"]  # shown, as context
    kinds = {v["kind"] for v in d["violations"]["new"]}
    assert "ramp_high" in kinds and "ratio_breach" not in kinds
    assert d["violations"]["resolved"] == []


# ── too little data ───────────────────────────────────────────────────────────────


def test_under_28_days_of_history_omits_load_instead_of_reporting_zero():
    rows = [run_row(1, TODAY - timedelta(days=10)), run_row(2, TODAY - timedelta(days=8))]
    d = digest([create()], rows=rows)
    assert d["sufficient"] is False and "load" in d["missing"]
    assert metric(d, "load.peak_ratio") is None
    assert metric(d, f"week.{WEEK}.volume")["delta"] == 0.75  # a plain sum is still real
    # The current week has only two weeks of history behind it: no baseline, so no ramp (None is
    # "not available", never a made-up zero).
    assert metric(d, f"week.{WEEK}.ramp") is None


def test_no_history_at_all_does_not_crash():
    d = digest([create()], rows=[])
    assert d["sufficient"] is False
    assert d["context"]["typical_week"] is None and "typical_week" in d["missing"]


# ── the change set matches the one the coach's tool builds ──────────────────────────


def test_changes_from_ops_matches_the_coach_tool_for_the_same_edit():
    """`_plan_ops` (update_training_plan) and `changes_from_ops` (what-if) must describe the same
    edit, or the preview and the commit would see different plans."""
    plan = [entry(1, FRIDAY), entry(2, FRIDAY + timedelta(days=1), "Long Run", 120)]
    args = {
        "set": [
            {"date": "2026-06-06", "workout_type": "Strength", "duration_min": 45},
            {"id": 1, "duration_min": 20, "date": "2026-06-04", "intensity": "hard"},
            {"date": "2026-06-07", "kind": "race", "sport": "run", "goal_time": "1:30:00"},
        ],
        "delete": [2],
    }
    ops, expected, errors = _plan_ops(args, plan)
    assert not errors
    assert changes_from_ops(ops, plan) == expected


# ── the coach's reply ───────────────────────────────────────────────────────────────


def reply(**over):
    return json.dumps(
        {
            "verdict": "fine",
            "headline": "Go ahead.",
            "reasons": [{"text": "Small.", "metric_ids": [f"week.{WEEK}.volume", "made.up"]}],
            "suggested": None,
            **over,
        }
    )


def test_a_good_reply_is_normalized_and_unknown_metric_ids_are_dropped():
    out = parse_what_if_response(reply(), digest([create()]))
    assert out["verdict"] == "fine" and out["headline"] == "Go ahead."
    assert out["reasons"] == [{"text": "Small.", "metric_ids": [f"week.{WEEK}.volume"]}]
    assert out["suggested"] is None


def test_the_reply_may_come_with_fences_or_prose_around_the_json():
    d = digest([create()])
    assert parse_what_if_response(f"```json\n{reply()}\n```", d)["verdict"] == "fine"
    assert (
        parse_what_if_response(f"Here you go: {reply()} Hope that helps.", d)["verdict"] == "fine"
    )


@pytest.mark.parametrize("text", ["fine!", "", "[1, 2]"])
def test_a_reply_with_no_json_object_raises(text):
    with pytest.raises((json.JSONDecodeError, TypeError)):
        parse_what_if_response(text, digest([create()]))


def test_an_unknown_verdict_becomes_a_caution_and_reasons_are_capped():
    many = [{"text": f"r{i}", "metric_ids": []} for i in range(9)] + ["junk", {"text": ""}]
    out = parse_what_if_response(reply(verdict="great", reasons=many), digest([create()]))
    assert out["verdict"] == "caution" and len(out["reasons"]) == MAX_REASONS


def test_the_verdict_is_never_milder_than_the_guardrails():
    blocked = digest([create()], prefs={"blocked_days": [FRIDAY.isoformat()]})
    assert verdict_floor(blocked) == "bad"
    assert parse_what_if_response(reply(verdict="fine"), blocked)["verdict"] == "bad"
    heavy = digest([create(TODAY + timedelta(days=i), "Easy Run", 240) for i in range(1, 8)])
    assert verdict_floor(heavy) == "caution"
    assert parse_what_if_response(reply(verdict="fine"), heavy)["verdict"] == "caution"
    assert parse_what_if_response(reply(verdict="bad"), heavy)["verdict"] == "bad"  # never lowered
    assert verdict_floor(digest([create()])) == "fine"


@pytest.mark.parametrize(
    "suggested,expected",
    [
        (None, None),
        ("do something", None),
        ({}, None),
        ({"set": [], "delete": []}, None),
        ({"set": "x"}, None),
        ({"delete": [3]}, {"set": [], "delete": [3]}),
        (
            {"set": [{"date": "2026-06-06"}], "delete": [3]},
            {"set": [{"date": "2026-06-06"}], "delete": [3]},
        ),
    ],
)
def test_the_suggestion_is_kept_only_when_it_is_a_change_set(suggested, expected):
    assert (
        parse_what_if_response(reply(suggested=suggested), digest([create()]))["suggested"]
        == expected
    )


def test_the_prompt_carries_the_numbers_the_neighbours_and_the_question():
    plan = [entry(7, FRIDAY - timedelta(days=1), "Tempo Run", 50, intensity="hard")]
    d = digest([create()], plan, prefs={"blocked_days": [(FRIDAY + timedelta(days=1)).isoformat()]})
    prompt = build_what_if_prompt(d, "Kettlebell after tempo?", "Name: Sam", ["- injury: knee"])
    for expected in (
        f"[week.{WEEK}.volume]",
        "2.83 h -> 3.58 h (+0.75 h)",  # the planned 50 min tempo is in both
        "[7] Thu 2026-06-04: Tempo Run",
        "[new] Fri 2026-06-05: Strength",
        "Blocked-out days: Sat 2026-06-06",
        "Name: Sam",
        "- injury: knee",
        "Kettlebell after tempo?",
    ):
        assert expected in prompt, expected
    assert "Is this a good idea?" in build_what_if_prompt(d, "   ")


# ── a structure decides the duration, as it does in storage ───────────────────────────


def test_a_structured_ride_without_a_duration_still_counts_by_its_structure():
    """STRUCTURE is one 4 h steady block. The change record must agree with the metrics: a ride
    the load model counts is never reported as having no duration."""
    op = create(wtype="Indoor Ride", minutes=None, structure=STRUCTURE)
    d = digest([op], mode="cycling")
    change = d["changes"][0]
    assert (change["hours"], change["counted"], change["reason"]) == (4.0, True, None)
    assert change["label"] == "Indoor Ride, 240 min"
    assert metric(d, f"week.{WEEK}.volume")["delta"] == 4.0


def test_a_structure_overrides_a_stated_duration_and_an_update_keeps_the_stored_one():
    stated = create(wtype="Indoor Ride", minutes=30, structure=STRUCTURE)
    assert digest([stated], mode="cycling")["changes"][0]["hours"] == 4.0
    stored = entry(9, FRIDAY, "Indoor Ride", 240, structure_json=json.dumps(STRUCTURE))
    d = digest([{"op": "update", "id": 9, "intensity": "hard"}], [stored], mode="cycling")
    assert d["changes"][0]["hours"] == 4.0 and d["changes"][0]["counted"] is True
