"""Unit tests for strides_ai.profile — all pure functions, no I/O."""

from strides_ai.profile import (
    _get_bullet,
    _get_pb,
    _get_section,
    _strip_comments,
    get_default_fields,
    parse_legacy_profile,
    profile_to_text,
)

# ── _strip_comments ───────────────────────────────────────────────────────────


def test_strip_comments_removes_inline():
    assert _strip_comments("hello <!-- world --> there") == "hello  there"


def test_strip_comments_multiline():
    s = "before\n<!-- line1\nline2 -->\nafter"
    assert _strip_comments(s) == "before\n\nafter"


def test_strip_comments_no_comments():
    assert _strip_comments("plain text") == "plain text"


def test_strip_comments_empty():
    assert _strip_comments("") == ""


def test_strip_comments_only_comment():
    assert _strip_comments("<!-- everything -->") == ""


# ── _get_section ──────────────────────────────────────────────────────────────

SAMPLE_DOC = """\
# Title

---

## Personal

- **Name:** Alice

---

## Running Background

- **Running since:** 2018

---

## Personal Bests

| Distance | Time |
|----------|------|
| 5K       | 19:30 |

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


def test_get_section_present():
    result = _get_section(SAMPLE_DOC, "Personal")
    assert "Name:" in result
    assert "Alice" in result


def test_get_section_missing():
    assert _get_section(SAMPLE_DOC, "Nonexistent") == ""


def test_get_section_case_insensitive():
    result = _get_section(SAMPLE_DOC, "personal")
    assert result != ""


def test_get_section_stops_at_next_separator():
    result = _get_section(SAMPLE_DOC, "Personal")
    assert "Running since" not in result


# ── _get_bullet ───────────────────────────────────────────────────────────────

PERSONAL_SECTION = """\
- **Name:** Alice
- **Gender:** Female
- **Date of birth:** 1990-05-15
- **Height:** 168 cm
- **Weight:** <!-- 60 kg -->
"""


def test_get_bullet_present():
    assert _get_bullet(PERSONAL_SECTION, "Name") == "Alice"


def test_get_bullet_missing():
    assert _get_bullet(PERSONAL_SECTION, "Shoe Size") == ""


def test_get_bullet_strips_comment():
    assert _get_bullet(PERSONAL_SECTION, "Weight") == ""


def test_get_bullet_case_insensitive():
    assert _get_bullet(PERSONAL_SECTION, "name") == "Alice"


def test_get_bullet_whitespace():
    section = "- **Name:**   Bob   "
    assert _get_bullet(section, "Name") == "Bob"


# ── _get_pb ───────────────────────────────────────────────────────────────────

PB_TABLE = """\
| Distance      | Time  |
|---------------|-------|
| 5K            | 19:30 |
| 10K           | 40:15 |
| Half marathon |       |
| Marathon      | 3:25:00 |
"""


def test_get_pb_present():
    assert _get_pb(PB_TABLE, "5K") == "19:30"


def test_get_pb_empty_cell():
    assert _get_pb(PB_TABLE, "Half marathon") == ""


def test_get_pb_missing_label():
    assert _get_pb(PB_TABLE, "Ultramarathon") == ""


def test_get_pb_skips_separator():
    table_with_separator_only = "| 5K | ------- |"
    assert _get_pb(table_with_separator_only, "5K") == ""


def test_get_pb_marathon():
    assert _get_pb(PB_TABLE, "Marathon") == "3:25:00"


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


# ── parse_legacy_profile ──────────────────────────────────────────────────────


def test_parse_legacy_profile_returns_all_keys():
    result = parse_legacy_profile(SAMPLE_DOC)
    assert set(result.keys()) == {
        "personal",
        "running_background",
        "personal_bests",
        "goals",
        "injuries_and_health",
        "gear",
        "other_notes",
    }


def test_parse_legacy_profile_personal_fields():
    result = parse_legacy_profile(SAMPLE_DOC)
    assert result["personal"]["name"] == "Alice"


def test_parse_legacy_profile_background():
    result = parse_legacy_profile(SAMPLE_DOC)
    assert result["running_background"]["running_since"] == "2018"


def test_parse_legacy_profile_pb():
    result = parse_legacy_profile(SAMPLE_DOC)
    assert result["personal_bests"]["5k"] == "19:30"


def test_parse_legacy_profile_goals():
    result = parse_legacy_profile(SAMPLE_DOC)
    assert "Race a 5K" in result["goals"]


def test_parse_legacy_profile_empty_string():
    result = parse_legacy_profile("")
    assert result["personal"]["name"] == ""
    assert result["goals"] == ""
