"""Dated coaching context shared by chat, plans, and activity analysis."""

from datetime import date, timedelta
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class MemoryTiming(BaseModel):
    status: Literal["current", "temporary", "superseded"] = "current"
    topic: str | None = Field(default=None, max_length=100)
    effective_from: date | None = None
    effective_until: date | None = None

    @model_validator(mode="after")
    def valid_window(self):
        if (
            self.effective_from
            and self.effective_until
            and self.effective_until < self.effective_from
        ):
            raise ValueError("End date must be on or after start date")
        if self.topic is not None:
            self.topic = self.topic.strip().lower() or None
        return self


def resolve_memories(memories: list[dict], today: date | None = None) -> list[dict]:
    """Return applicable facts; temporary overrides win within an explicitly shared topic.

    Dates are inclusive. An undated legacy fact stays applicable until reviewed.
    Unrelated facts in the same category never replace each other.
    """
    day = (today or date.today()).isoformat()
    eligible = [
        m
        for m in memories
        if m.get("status", "current") != "superseded"
        and (not m.get("effective_from") or str(m["effective_from"]) <= day)
        and (not m.get("effective_until") or str(m["effective_until"]) >= day)
    ]
    winners = {}
    for m in eligible:
        topic = m.get("topic")
        if not topic:
            continue
        key = (
            str(m.get("effective_from") or ""),
            m.get("status") == "temporary",
            str(m.get("created_at") or ""),
            m.get("id") or 0,
        )
        if topic not in winners or key > winners[topic][0]:
            winners[topic] = (key, m)
    return [m for m in eligible if not m.get("topic") or winners[m["topic"]][1] is m]


NOTES_HEADER = (
    "## Coaching Notes (remembered from previous sessions)\n"
    "These are the applicable dated facts. They take precedence over conflicting older "
    "profile goals/preferences and recalled conversations. Temporary facts override only "
    "their topic; do not treat them as permanent changes. Do not revive expired or "
    "superseded instructions from conversation history. Undated facts may be stale: "
    "prefer explicit newer statements and ask when a conflict is unresolved."
)
# Lower comes first when notes must be cut: a note's category decides what is kept longest.
CATEGORY_RANK = ("injury", "race", "goal", "training", "preference", "other")


def memory_line(m: dict) -> str:
    timing = f"{m.get('status', 'current')}; from {m.get('effective_from') or 'unspecified'}; until {m.get('effective_until') or 'ongoing'}"
    topic = f"; topic={m['topic']}" if m.get("topic") else ""
    return f"  [{m['category']}] {m['content']} (id={m.get('id', '?')}; {timing}{topic})"


def is_protected(m: dict) -> bool:
    """Notes about an injury, or a temporary override, are never cut from the prompt."""
    return m.get("category") == "injury" or m.get("status") == "temporary"


def memory_rank_key(m: dict):
    """Sort key, best first: category, then effective_from newest first (undated last), then id
    newest first."""
    category = m.get("category")
    cat = CATEGORY_RANK.index(category) if category in CATEGORY_RANK else len(CATEGORY_RANK)
    try:
        day = date.fromisoformat(str(m.get("effective_from"))[:10])
    except ValueError:
        day = None
    return (
        cat,
        day is None,
        -(day.toordinal() if day else 0),
        -(m.get("id") if type(m.get("id")) is int else 0),
    )


def split_memories(memories: list[dict], today: date | None = None) -> tuple[list[str], list[str]]:
    """The applicable notes as prompt lines: (protected, others by rank, best first)."""
    active = sorted(resolve_memories(memories, today), key=memory_rank_key)
    return (
        [memory_line(m) for m in active if is_protected(m)],
        [memory_line(m) for m in active if not is_protected(m)],
    )


def memories_section(memories: list[dict], today: date | None = None) -> str:
    active = resolve_memories(memories, today)
    if not memories:
        return ""
    return "\n".join([NOTES_HEADER, *(memory_line(m) for m in active)])


def memory_timeline_section(memories: list[dict], start: date, end: date) -> str:
    """Resolve context at each change boundary within a requested training block."""
    if not memories:
        return ""
    boundaries = {start}
    for m in memories:
        for field in ("effective_from", "effective_until"):
            if m.get(field):
                boundary = date.fromisoformat(str(m[field]))
                if field == "effective_until":
                    if boundary == date.max:
                        continue
                    boundary += timedelta(days=1)
                if start < boundary <= end:
                    boundaries.add(boundary)
    points = sorted(boundaries)
    sections = [
        "## Dated coaching context for the requested block",
        "Apply each period's context only to workouts within that period.",
    ]
    for i, point in enumerate(points):
        through = points[i + 1] - timedelta(days=1) if i + 1 < len(points) else end
        sections.append(
            f"### {point.isoformat()} through {through.isoformat()}\n"
            + memories_section(memories, point)
        )
    return "\n\n".join(sections)
