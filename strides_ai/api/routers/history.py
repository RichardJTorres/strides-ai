"""Conversation history routes."""

from fastapi import APIRouter, Depends
from sqlmodel import Session

from ...coach import RECALL_MESSAGES
from ...db import conversations as crud
from ...db.engine import get_session

router = APIRouter()


@router.get("/history")
def history(
    limit: int = RECALL_MESSAGES,
    mode: str | None = None,
    session: Session = Depends(get_session),
):
    messages = [r.model_dump() for r in crud.get_recent(session, limit, mode=mode)]
    total = crud.count(session, mode=mode)
    return {"messages": messages, "total": total}


@router.get("/history/older")
def history_older(
    before_id: int,
    limit: int = 40,
    mode: str | None = None,
    session: Session = Depends(get_session),
):
    messages = [r.model_dump() for r in crud.get_before(session, before_id, limit, mode=mode)]
    return {"messages": messages}


@router.get("/history/search")
def history_search(
    q: str,
    limit: int = 20,
    mode: str | None = None,
    session: Session = Depends(get_session),
):
    if not q or not q.strip():
        return {"results": []}
    return {"results": [r.model_dump() for r in crud.search(session, q.strip(), limit, mode=mode)]}
