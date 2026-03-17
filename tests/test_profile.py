"""Unit tests for strides_ai.profile — all pure functions, no I/O."""

from strides_ai.profile import (
    get_default_fields,
    profile_to_text,
)


# ── get_default_fields ────────────────────────────────────────────────────────


def test_get_default_fields_running_keys():
    fields = get_default_fields("running")
    assert set(fields.keys()) == {
        "personal",
        "running_background",
        "personal_bests",
        "goals",
        "injuries_and_health",
        "gear",
        "nutrition_snacks",
        "other_notes",
    }


def test_get_default_fields_cycling_keys():
    fields = get_default_fields("cycling")
    assert set(fields.keys()) == {
        "personal",
        "cycling_background",
        "cycling_bests",
        "goals",
        "injuries_and_health",
        "gear",
        "nutrition_snacks",
        "other_notes",
    }


def test_get_default_fields_hybrid_keys():
    fields = get_default_fields("hybrid")
    assert "running_background" in fields
    assert "cycling_background" in fields
    assert "running_bests" in fields
    assert "cycling_bests" in fields


def test_get_default_fields_returns_empty_strings():
    fields = get_default_fields("running")
    assert fields["personal"]["name"] == ""
    assert fields["personal_bests"]["5k"] == ""
    assert fields["goals"] == ""


def test_get_default_fields_returns_deep_copy():
    f1 = get_default_fields("running")
    f2 = get_default_fields("running")
    f1["personal"]["name"] = "Alice"
    assert f2["personal"]["name"] == ""


def test_get_default_fields_unknown_mode_falls_back_to_running():
    fields = get_default_fields("triathlon")
    assert "running_background" in fields
    assert "personal_bests" in fields


# ── profile_to_text ───────────────────────────────────────────────────────────


def test_profile_to_text_none_returns_empty():
    assert profile_to_text(None, "running") == ""


def test_profile_to_text_all_blank_returns_empty():
    fields = get_default_fields("running")
    assert profile_to_text(fields, "running") == ""


def test_profile_to_text_name_appears():
    fields = get_default_fields("running")
    fields["personal"]["name"] = "Alice"
    result = profile_to_text(fields, "running")
    assert "Alice" in result


def test_profile_to_text_running_pb_appears():
    fields = get_default_fields("running")
    fields["personal_bests"]["5k"] = "19:30"
    result = profile_to_text(fields, "running")
    assert "19:30" in result


def test_profile_to_text_goals_appear():
    fields = get_default_fields("running")
    fields["goals"] = "Sub-3 marathon"
    result = profile_to_text(fields, "running")
    assert "Sub-3 marathon" in result


def test_profile_to_text_cycling_fields():
    fields = get_default_fields("cycling")
    fields["cycling_bests"]["ftp"] = "280 W"
    result = profile_to_text(fields, "cycling")
    assert "280 W" in result


def test_profile_to_text_hybrid_includes_both():
    fields = get_default_fields("hybrid")
    fields["running_background"]["running_since"] = "2015"
    fields["cycling_background"]["cycling_since"] = "2020"
    result = profile_to_text(fields, "hybrid")
    assert "2015" in result
    assert "2020" in result


def test_profile_to_text_skips_blank_fields():
    fields = get_default_fields("running")
    fields["personal"]["name"] = "Bob"
    result = profile_to_text(fields, "running")
    # gender is blank — should not appear
    assert "Gender" not in result


def test_profile_to_text_nutrition_snacks_appear():
    fields = get_default_fields("running")
    fields["nutrition_snacks"] = ["banana", "gel"]
    result = profile_to_text(fields, "running")
    assert "banana" in result
    assert "gel" in result
