"""Unit tests for strides_ai.profile — all pure functions, no I/O.

The profile module has two concerns:
  1. Structured field schema (get_default_fields) and LLM text rendering
     (profile_to_text) — the current primary API, backed by DB storage.
  2. parse_legacy_profile — a one-time migration helper that converts the old
     profile.md Markdown format into the structured fields dict on first server
     startup.
"""

from strides_ai.profile import (
    get_default_fields,
    parse_legacy_profile,
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


# ── parse_legacy_profile ──────────────────────────────────────────────────────
# One-time migration helper: reads the old profile.md Markdown format and
# returns a running-schema fields dict. Used in server.py on first startup
# when a profile.md exists but no DB profile has been saved yet.

LEGACY_DOC = """\
# Title

---

## Personal

- **Name:** Alice
- **Gender:** Female
- **Date of birth:** 1990-05-15

---

## Running Background

- **Running since:** 2018
- **Typical weekly volume:** 60 km

---

## Personal Bests

| Distance | Time |
|----------|------|
| 5K       | 19:30 |
| Marathon | 3:25:00 |

---

## Goals

Race a 5K in under 18 minutes.

---

## Injuries & Health

None.

---

## Gear

Trail shoes.

---

## Other Notes

Morning runner.
"""


def test_parse_legacy_profile_personal_fields():
    result = parse_legacy_profile(LEGACY_DOC)
    assert result["personal"]["name"] == "Alice"
    assert result["personal"]["gender"] == "Female"


def test_parse_legacy_profile_background():
    result = parse_legacy_profile(LEGACY_DOC)
    assert result["running_background"]["running_since"] == "2018"


def test_parse_legacy_profile_pbs():
    result = parse_legacy_profile(LEGACY_DOC)
    assert result["personal_bests"]["5k"] == "19:30"
    assert result["personal_bests"]["marathon"] == "3:25:00"


def test_parse_legacy_profile_goals():
    result = parse_legacy_profile(LEGACY_DOC)
    assert "Race a 5K" in result["goals"]


def test_parse_legacy_profile_empty_string():
    result = parse_legacy_profile("")
    assert result["personal"]["name"] == ""
    assert result["goals"] == ""


def test_parse_legacy_profile_returns_running_schema_keys():
    result = parse_legacy_profile(LEGACY_DOC)
    assert set(result.keys()) == {
        "personal",
        "running_background",
        "personal_bests",
        "goals",
        "injuries_and_health",
        "gear",
        "other_notes",
    }


def test_parse_legacy_profile_strips_html_comments():
    doc = "## Goals\n\nSub-3 marathon <!-- private note -->\n"
    result = parse_legacy_profile(doc)
    assert "private note" not in result["goals"]
    assert "Sub-3 marathon" in result["goals"]
