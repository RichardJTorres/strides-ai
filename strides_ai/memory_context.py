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


def memories_section(memories: list[dict], today: date | None = None) -> str:
    active = resolve_memories(memories, today)
    if not memories:
        return ""
    lines = [
        "## Coaching Notes (remembered from previous sessions)",
        "These are the applicable dated facts. They take precedence over conflicting older "
        "profile goals/preferences and recalled conversations. Temporary facts override only "
        "their topic; do not treat them as permanent changes. Do not revive expired or "
        "superseded instructions from conversation history. Undated facts may be stale: "
        "prefer explicit newer statements and ask when a conflict is unresolved.",
    ]
    for m in active:
        timing = f"{m.get('status', 'current')}; from {m.get('effective_from') or 'unspecified'}; until {m.get('effective_until') or 'ongoing'}"
        topic = f"; topic={m['topic']}" if m.get("topic") else ""
        lines.append(f"  [{m['category']}] {m['content']} (id={m.get('id', '?')}; {timing}{topic})")
    return "\n".join(lines)


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
