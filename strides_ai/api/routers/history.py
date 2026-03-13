"""Conversation history routes."""

from fastapi import APIRouter

from ... import db
from ...coach import RECALL_MESSAGES

router = APIRouter()


@router.get("/history")
def history(limit: int = RECALL_MESSAGES, mode: str | None = None):
    messages = db.get_recent_messages(limit, mode=mode)
    total = db.get_message_count(mode=mode)
    return {"messages": messages, "total": total}


@router.get("/history/older")
def history_older(before_id: int, limit: int = 40, mode: str | None = None):
    messages = db.get_messages_before(before_id, limit, mode=mode)
    return {"messages": messages}


@router.get("/history/search")
def history_search(q: str, limit: int = 20, mode: str | None = None):
    if not q or not q.strip():
        return {"results": []}
    return {"results": db.search_messages(q.strip(), limit, mode=mode)}
