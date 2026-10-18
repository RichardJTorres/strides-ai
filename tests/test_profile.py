"""Unit tests for strides_ai.profile — the unified, mode-scoped athlete profile."""

import pytest

from strides_ai.profile import (
    DISCIPLINES_BY_MODE,
    build_profile_proposal,
    get_default_fields,
    profile_completeness,
    profile_to_text,
    with_defaults,
)

# ── defaults ──────────────────────────────────────────────────────────────────


def test_default_fields_structure():
    d = get_default_fields()
    assert set(d) >= {"personal", "goals", "availability", "injuries_and_health", "running"}
    assert set(d["running"]["bests"]) == {"5k", "10k", "half_marathon", "marathon"}
    assert "squat_1rm" in d["lifting"]["bests"]
    assert d["personal"]["max_hr"] is None


def test_default_fields_returns_deep_copy():
    d = get_default_fields()
    d["running"]["bests"]["5k"] = "20:00"
    d["availability"]["preferred_days"].append("mon")
    fresh = get_default_fields()
    assert fresh["running"]["bests"]["5k"] == ""
    assert fresh["availability"]["preferred_days"] == []


def test_with_defaults_overlays_nested_values():
    doc = with_defaults({"running": {"bests": {"5k": "20:00"}}, "goals": "sub-3"})
    assert doc["running"]["bests"] == {
        "5k": "20:00",
        "10k": "",
        "half_marathon": "",
        "marathon": "",
    }
    assert doc["goals"] == "sub-3"
    assert doc["cycling"]["since"] == ""


def test_hybrid_is_running_plus_cycling():
    assert DISCIPLINES_BY_MODE["hybrid"] == ("running", "cycling")


# ── profile_to_text ───────────────────────────────────────────────────────────


def test_profile_to_text_none_and_blank_return_empty():
    assert profile_to_text(None, "running") == ""
    assert profile_to_text(get_default_fields(), "running") == ""


def test_shared_fields_appear_in_every_mode():
    fields = {
        "personal": {"name": "Alice", "max_hr": 188},
        "goals": "Sub-3 marathon",
        "injuries_and_health": "Left knee",
        "availability": {"sessions_per_week": 5, "preferred_days": ["sat", "mon"]},
    }
    for mode in DISCIPLINES_BY_MODE:
        text = profile_to_text(fields, mode)
        assert "Name: Alice" in text and "Max heart rate: 188 bpm" in text
        assert "Sub-3 marathon" in text and "Left knee" in text
        assert "Sessions per week: 5" in text
        assert "Preferred training days: Mon, Sat" in text  # canonical weekday order


def test_active_discipline_is_rendered_in_full_and_others_summarised():
    fields = {
        "running": {"bests": {"5k": "19:30"}, "focus": "trail", "gear": "Speedgoat 5"},
        "lifting": {"volume": "3", "bests": {"squat_1rm": "140 kg"}, "gear": "Home gym"},
    }
    text = profile_to_text(fields, "running")
    assert "### Running Bests\n5K: 19:30" in text
    assert "Running focus: Trail Running" in text
    assert "### Gear\nSpeedgoat 5" in text
    assert "### Also Trains" in text
    assert "Lifting: sessions per week: 3; Squat 1RM: 140 kg" in text
    assert "Home gym" not in text  # inactive discipline's gear is not rendered

    lifting = profile_to_text(fields, "lifting")
    assert "### Lifting Bests\nSquat 1RM: 140 kg" in lifting
    assert "### Equipment\nHome gym" in lifting
    assert "Running: " in lifting.split("### Also Trains")[1]


def test_hybrid_renders_running_and_cycling_without_also_trains():
    fields = {
        "running": {"bests": {"5k": "20:00"}, "gear": "Road shoes"},
        "cycling": {"bests": {"ftp": "250 W"}, "gear": "Gravel bike"},
    }
    text = profile_to_text(fields, "hybrid")
    assert "Running Bests" in text and "Cycling Bests" in text
    assert "### Running gear\nRoad shoes" in text and "### Cycling gear\nGravel bike" in text
    assert "Also Trains" not in text


def test_profile_to_text_is_deterministic_and_skips_blank_fields():
    fields = {"goals": "Base", "running": {"since": "2015", "volume": ""}}
    assert profile_to_text(fields, "running") == profile_to_text(
        dict(reversed(fields.items())), "running"
    )
    text = profile_to_text(fields, "running")
    assert "Running since: 2015" in text and "Weekly volume" not in text


def test_nutrition_snacks_appear_as_bullets():
    text = profile_to_text({"nutrition_snacks": ["Gels", " ", "Bananas"]}, "running")
    assert "- Gels" in text and "- Bananas" in text


# ── completeness ──────────────────────────────────────────────────────────────


def test_completeness_empty_profile():
    c = profile_completeness(None, "running")
    assert c["percent"] == 0
    assert c["missing"][0]["weight"] == 3 and c["missing"][0]["path"] == "goals"


def test_completeness_is_scoped_to_the_mode_and_deterministic():
    fields = {"goals": "x", "lifting": {"since": "2020"}}
    running = profile_completeness(fields, "running")
    lifting = profile_completeness(fields, "lifting")
    assert all(not m["path"].startswith("lifting.") for m in running["missing"])
    assert any(m["path"] == "lifting.volume" for m in lifting["missing"])
    assert lifting["percent"] > running["percent"] or running["percent"] != lifting["percent"]
    assert profile_completeness(fields, "running") == running


# ── update_profile proposals ──────────────────────────────────────────────────


def test_proposal_set_text_field_builds_put_body():
    p = build_profile_proposal({"field": "goals", "value": "Run Boston"}, None)
    assert p["section"] == "shared" and p["fields"] == {"goals": "Run Boston"}
    assert p["current"] is None


def test_proposal_append_resolves_against_current_value():
    current = {"injuries_and_health": "Left knee"}
    p = build_profile_proposal(
        {"field": "injuries_and_health", "value": "Plantar fasciitis", "op": "append"}, current
    )
    assert p["fields"] == {"injuries_and_health": "Left knee\nPlantar fasciitis"}
    assert p["current"] == "Left knee"


def test_proposal_discipline_best_and_section():
    p = build_profile_proposal({"field": "running.bests.5k", "value": "19:30"}, None)
    assert p["section"] == "running" and p["fields"] == {"bests": {"5k": "19:30"}}


def test_proposal_typed_fields():
    assert (
        build_profile_proposal({"field": "personal.max_hr", "value": "187"}, None)["fields"][
            "personal"
        ]["max_hr"]
        == 187
    )
    days = build_profile_proposal(
        {"field": "availability.preferred_days", "value": "Sat, mon"}, None
    )
    assert days["fields"]["availability"]["preferred_days"] == ["mon", "sat"]
    focus = build_profile_proposal({"field": "running.focus", "value": "Trail Running"}, None)
    assert focus["proposed"] == "trail"
    assert (
        build_profile_proposal({"field": "running.focus", "value": "ultra"}, None)["proposed"]
        == "ultra"
    )


@pytest.mark.parametrize(
    "args",
    [
        {"field": "coach_voice", "value": "x"},  # not whitelisted
        {"field": "running.bests.nope", "value": "x"},
        {"field": "goals", "value": ""},
        {"field": "goals", "value": "x", "op": "delete"},
        {"field": "personal.max_hr", "value": "40"},
        {"field": "personal.max_hr", "value": "fast"},
        {"field": "availability.preferred_days", "value": "funday"},
        {"field": "running.focus", "value": "spelunking"},
    ],
)
def test_invalid_proposals_raise(args):
    with pytest.raises(ValueError):
        build_profile_proposal(args, None)
