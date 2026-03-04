"""Athlete profile — loaded from a user-editable Markdown file."""

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
