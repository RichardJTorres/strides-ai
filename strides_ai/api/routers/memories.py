"""Memories route."""

import json
import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field, ValidationError
from sqlmodel import Session

from ...db import memories as crud
from ...memory_context import MemoryTiming, resolve_memories
from datetime import date
from sqlalchemy.exc import IntegrityError
from ...db.engine import get_session
from ..deps import get_backend

router = APIRouter()

VALID_CATEGORIES = {"goal", "race", "injury", "preference", "training", "other"}

REVIEW_SYSTEM = """\
You are a memory curator for an AI athletic coaching app. Your job is to review a list of
remembered facts about an athlete and identify any that may be stale, outdated, resolved,
or superseded.

You must respond with ONLY a valid JSON array — no prose, no markdown fences, no explanation.
Each element must be an object with exactly two keys:
  "id"     – integer, the id of the memory
  "reason" – string, one concise sentence explaining why this memory may be worth removing

Only include memories that genuinely seem outdated or no longer useful. If all memories look
current and relevant, return an empty array: []

Be conservative — when in doubt, leave a memory in."""


def _build_review_prompt(memories: list[dict]) -> str:
    lines = [
        f'  id={m["id"]}  [{m["category"]}; {m.get("status", "current")}; from={m.get("effective_from")}; until={m.get("effective_until")}]  {m["content"]}'
        for m in memories
    ]
    return (
        f"Today is {date.today().isoformat()}. Profile and memory facts may conflict. "
        + "Review dates and states; recommend archiving stale facts rather than deleting history.\n"
        + "\n".join(lines)
    )


def _parse_review_json(text: str) -> list[dict]:
    """Extract and parse a JSON array from the model's response."""
    # Strip any accidental markdown fences
    text = re.sub(r"```[a-z]*\n?", "", text).strip()
    return json.loads(text)


class MemoryUpdate(MemoryTiming):
    category: str
    content: str = Field(min_length=1)


@router.get("/memories")
def get_memories(session: Session = Depends(get_session)):
    memories = [r.model_dump() for r in crud.get_all(session)]
    active_ids = {m["id"] for m in resolve_memories(memories)}
    return [{**m, "applicable": m["id"] in active_ids} for m in memories]


@router.post("/memories/review")
def review_memories(session: Session = Depends(get_session), backend=Depends(get_backend)):
    memories = crud.get_all(session)
    if not memories:
        return []

    memory_dicts = [m.model_dump() for m in memories if m.status != "superseded"]
    prompt = _build_review_prompt(memory_dicts)

    try:
        raw = backend.stateless_turn(REVIEW_SYSTEM, prompt, lambda _: None)
        flagged = _parse_review_json(raw)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Model review failed: {exc}")

    # Attach full memory details to each flagged item
    by_id = {m["id"]: m for m in memory_dicts}
    result = []
    for item in flagged:
        mem_id = item.get("id")
        if mem_id in by_id:
            result.append({**by_id[mem_id], "reason": item.get("reason", "")})

    return result


@router.put("/memories/{memory_id}")
def update_memory(memory_id: int, body: MemoryUpdate, session: Session = Depends(get_session)):
    if body.category not in VALID_CATEGORIES:
        raise HTTPException(status_code=422, detail=f"Invalid category: {body.category}")
    if not body.content.strip():
        raise HTTPException(status_code=422, detail="Memory content cannot be empty")
    metadata = body.model_dump(mode="json", exclude={"category", "content"}, exclude_unset=True)
    try:
        memory = crud.update(session, memory_id, body.category, body.content.strip(), **metadata)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except IntegrityError:
        session.rollback()
        raise HTTPException(status_code=409, detail="A memory with this content already exists")
    if memory is None:
        raise HTTPException(status_code=404, detail="Memory not found")
    memories = [m.model_dump() for m in crud.get_all(session)]
    active_ids = {m["id"] for m in resolve_memories(memories)}
    return {**memory.model_dump(), "applicable": memory.id in active_ids}


@router.delete("/memories/{memory_id}", status_code=204)
def delete_memory(memory_id: int, session: Session = Depends(get_session)):
    if not crud.delete(session, memory_id):
        raise HTTPException(status_code=404, detail="Memory not found")
