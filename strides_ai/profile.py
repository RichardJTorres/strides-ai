"""Athlete profile — loaded from a user-editable Markdown file."""

import re
from pathlib import Path

PROFILE_PATH = Path.home() / ".strides_ai" / "profile.md"

TEMPLATE = """\
# Athlete Profile

Edit this file freely. It is read at the start of every session and sent to
your coach as context. Write in plain language — the more detail you provide,
the more personalised your coaching will be.

---

## Personal

- **Name:**
- **Gender:**
- **Date of birth:** <!-- e.g. 1990-05-15 -->
- **Height:**
- **Weight:**

---

## Running Background

<!-- How long have you been running? What's your athletic history?
     Previous race experience, how you got into the sport, etc. -->

- **Running since:**
- **Typical weekly volume:**
- **Background:**

---

## Personal Bests

| Distance      | Time  |
|---------------|-------|
| 5K            |       |
| 10K           |       |
| Half marathon |       |
| Marathon      |       |

---

## Goals

<!-- Upcoming target races, time goals, non-race goals (e.g. lose weight,
     run consistently, complete first marathon) -->

---

## Injuries & Health

<!-- Current or recurring injuries, medical conditions, medications,
     or anything else your coach should know for safe training advice -->

---

## Other Notes

<!-- Preferred training times, coaching style preferences, recent life
     changes affecting training, anything else relevant -->
"""


def ensure_profile_file() -> bool:
    """
    Create the profile file from the template if it doesn't exist.
    Returns True if newly created, False if it already existed.
    """
    if PROFILE_PATH.exists():
        return False
    PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROFILE_PATH.write_text(TEMPLATE)
    return True


def load_profile() -> str:
    """
    Read and return the raw profile text.
    Returns an empty string if the file doesn't exist or is blank.
    """
    if not PROFILE_PATH.exists():
        return ""
    return PROFILE_PATH.read_text().strip()


# ── Structured parse / serialize ─────────────────────────────────────────────

def _get_section(text: str, name: str) -> str:
    """Extract the body of a ## Section, stopping at the next --- or ##."""
    pattern = rf'##\s+{re.escape(name)}\s*\n(.*?)(?=\n---|\n##|\Z)'
    m = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
    return m.group(1).strip() if m else ""


def _strip_comments(s: str) -> str:
    return re.sub(r'<!--.*?-->', '', s, flags=re.DOTALL).strip()


def _get_bullet(section_text: str, field_name: str) -> str:
    """Extract the value from a '- **FieldName:** value' bullet line."""
    pattern = rf'^\s*-\s+\*\*{re.escape(field_name)}:\*\*\s*(.*?)$'
    m = re.search(pattern, section_text, re.MULTILINE | re.IGNORECASE)
    if not m:
        return ""
    return _strip_comments(m.group(1)).strip()


def _get_pb(pbs_text: str, label: str) -> str:
    """Extract a time value from a personal bests table row."""
    pattern = rf'\|\s*{re.escape(label)}\s*\|\s*(.*?)\s*\|'
    for m in re.finditer(pattern, pbs_text, re.IGNORECASE):
        val = m.group(1).strip()
        if not re.fullmatch(r'[-:]+', val):  # skip separator rows
            return val
    return ""


def parse_profile(text: str) -> dict:
    """Parse profile Markdown into a structured fields dict."""
    personal = _get_section(text, "Personal")
    background = _get_section(text, "Running Background")
    pbs = _get_section(text, "Personal Bests")

    return {
        "personal": {
            "name": _get_bullet(personal, "Name"),
            "gender": _get_bullet(personal, "Gender"),
            "date_of_birth": _get_bullet(personal, "Date of birth"),
            "height": _get_bullet(personal, "Height"),
            "weight": _get_bullet(personal, "Weight"),
        },
        "running_background": {
            "running_since": _get_bullet(background, "Running since"),
            "weekly_volume": _get_bullet(background, "Typical weekly volume"),
            "background": _get_bullet(background, "Background"),
        },
        "personal_bests": {
            "5k": _get_pb(pbs, "5K"),
            "10k": _get_pb(pbs, "10K"),
            "half_marathon": _get_pb(pbs, "Half marathon"),
            "marathon": _get_pb(pbs, "Marathon"),
        },
        "goals": _strip_comments(_get_section(text, "Goals")),
        "injuries_and_health": _strip_comments(_get_section(text, "Injuries & Health")),
        "other_notes": _strip_comments(_get_section(text, "Other Notes")),
    }


def serialize_profile(fields: dict) -> str:
    """Serialize a structured fields dict back to profile Markdown."""
    p = fields.get("personal", {})
    bg = fields.get("running_background", {})
    pbs = fields.get("personal_bests", {})

    def v(val) -> str:
        return (val or "").strip()

    return (
        "# Athlete Profile\n\n"
        "Edit this file freely. It is read at the start of every session and sent to\n"
        "your coach as context. Write in plain language — the more detail you provide,\n"
        "the more personalised your coaching will be.\n\n"
        "---\n\n"
        "## Personal\n\n"
        f"- **Name:** {v(p.get('name'))}\n"
        f"- **Gender:** {v(p.get('gender'))}\n"
        f"- **Date of birth:** {v(p.get('date_of_birth'))}\n"
        f"- **Height:** {v(p.get('height'))}\n"
        f"- **Weight:** {v(p.get('weight'))}\n\n"
        "---\n\n"
        "## Running Background\n\n"
        f"- **Running since:** {v(bg.get('running_since'))}\n"
        f"- **Typical weekly volume:** {v(bg.get('weekly_volume'))}\n"
        f"- **Background:** {v(bg.get('background'))}\n\n"
        "---\n\n"
        "## Personal Bests\n\n"
        "| Distance      | Time  |\n"
        "|---------------:|-------|\n"
        f"| 5K            | {v(pbs.get('5k'))} |\n"
        f"| 10K           | {v(pbs.get('10k'))} |\n"
        f"| Half marathon | {v(pbs.get('half_marathon'))} |\n"
        f"| Marathon      | {v(pbs.get('marathon'))} |\n\n"
        "---\n\n"
        "## Goals\n\n"
        f"{v(fields.get('goals'))}\n\n"
        "---\n\n"
        "## Injuries & Health\n\n"
        f"{v(fields.get('injuries_and_health'))}\n\n"
        "---\n\n"
        "## Other Notes\n\n"
        f"{v(fields.get('other_notes'))}\n"
    )
