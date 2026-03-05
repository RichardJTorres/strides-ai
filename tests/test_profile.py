"""Unit tests for strides_ai.profile — all pure functions, no I/O."""

import pytest

from strides_ai.profile import (
    TEMPLATE,
    _get_bullet,
    _get_pb,
    _get_section,
    _strip_comments,
    is_parseable,
    parse_profile,
    serialize_profile,
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
    # A row where the time cell is all dashes/colons is treated as a separator and skipped.
    # In PB_TABLE the header row `| Distance | Time |` has a non-dash time cell ("Time"),
    # so _get_pb("Distance") returns "Time" (header) — but separator cells like "-------"
    # are skipped. Verify the actual separator row in the table is not returned for 5K.
    table_with_separator_only = "| 5K | ------- |"
    assert _get_pb(table_with_separator_only, "5K") == ""


def test_get_pb_marathon():
    assert _get_pb(PB_TABLE, "Marathon") == "3:25:00"


# ── is_parseable ──────────────────────────────────────────────────────────────

def test_is_parseable_template():
    assert is_parseable(TEMPLATE) is True


def test_is_parseable_missing_section():
    broken = TEMPLATE.replace("## Personal Bests", "## PR Table")
    assert is_parseable(broken) is False


def test_is_parseable_empty():
    assert is_parseable("") is False


def test_is_parseable_sample_doc():
    assert is_parseable(SAMPLE_DOC) is True


# ── parse_profile ─────────────────────────────────────────────────────────────

def test_parse_profile_returns_all_keys():
    result = parse_profile(TEMPLATE)
    assert set(result.keys()) == {
        "personal", "running_background", "personal_bests",
        "goals", "injuries_and_health", "gear", "other_notes",
    }
    assert set(result["personal"].keys()) == {"name", "gender", "date_of_birth", "height", "weight"}
    assert set(result["personal_bests"].keys()) == {"5k", "10k", "half_marathon", "marathon"}


def test_parse_profile_blank_values_from_template():
    result = parse_profile(TEMPLATE)
    assert result["personal"]["name"] == ""
    assert result["personal_bests"]["5k"] == ""


def test_parse_profile_filled_values():
    result = parse_profile(SAMPLE_DOC)
    assert result["personal"]["name"] == "Alice"
    assert result["running_background"]["running_since"] == "2018"
    assert result["personal_bests"]["5k"] == "19:30"


def test_parse_profile_goals_strip_comments():
    doc = SAMPLE_DOC  # Goals section has no comments
    result = parse_profile(doc)
    assert "Race a 5K" in result["goals"]


# ── serialize_profile / roundtrip ─────────────────────────────────────────────

def test_serialize_profile_contains_sections():
    fields = parse_profile(TEMPLATE)
    out = serialize_profile(fields)
    assert "## Personal" in out
    assert "## Running Background" in out
    assert "## Personal Bests" in out
    assert "## Goals" in out
    assert "## Injuries & Health" in out
    assert "## Gear" in out
    assert "## Other Notes" in out


def test_serialize_roundtrip():
    """parse → serialize → parse should produce equivalent dicts."""
    fields1 = parse_profile(SAMPLE_DOC)
    serialized = serialize_profile(fields1)
    fields2 = parse_profile(serialized)
    assert fields2["personal"]["name"] == fields1["personal"]["name"]
    assert fields2["personal_bests"]["5k"] == fields1["personal_bests"]["5k"]
    assert fields2["running_background"]["running_since"] == fields1["running_background"]["running_since"]


def test_serialize_preserves_pb_values():
    fields = {
        "personal": {"name": "Bob", "gender": "Male", "date_of_birth": "", "height": "", "weight": ""},
        "running_background": {"running_since": "2020", "weekly_volume": "50km", "background": ""},
        "personal_bests": {"5k": "18:00", "10k": "37:30", "half_marathon": "1:22:00", "marathon": ""},
        "goals": "BQ",
        "injuries_and_health": "",
        "gear": "",
        "other_notes": "",
    }
    out = serialize_profile(fields)
    parsed = parse_profile(out)
    assert parsed["personal"]["name"] == "Bob"
    assert parsed["personal_bests"]["5k"] == "18:00"
    assert parsed["personal_bests"]["marathon"] == ""
    assert parsed["goals"] == "BQ"
