"""Conversation history CRUD operations."""

import sqlalchemy as sa
from sqlmodel import Session, select

from .models import Conversation


def save(
    session: Session,
    role: str,
    content: str,
    mode: str = "running",
    model: str | None = None,
) -> None:
    session.add(Conversation(role=role, content=content, mode=mode, model=model))
    session.commit()


def get_recent(session: Session, n: int = 40, mode: str | None = None) -> list[Conversation]:
    """Return the last *n* messages in chronological order, optionally filtered by mode."""
    stmt = select(Conversation).order_by(Conversation.id.desc()).limit(n)
    if mode:
        stmt = stmt.where(Conversation.mode == mode)
    rows = session.exec(stmt).all()
    return list(reversed(rows))


def get_before(
    session: Session,
    before_id: int,
    limit: int = 40,
    mode: str | None = None,
) -> list[Conversation]:
    """Return up to *limit* messages with id < before_id, in chronological order."""
    stmt = (
        select(Conversation)
        .where(Conversation.id < before_id)
        .order_by(Conversation.id.desc())
        .limit(limit)
    )
    if mode:
        stmt = stmt.where(Conversation.mode == mode)
    rows = session.exec(stmt).all()
    return list(reversed(rows))


def count(session: Session, mode: str | None = None) -> int:
    """Return the total number of stored messages, optionally filtered by mode."""
    stmt = select(sa.func.count()).select_from(Conversation)
    if mode:
        stmt = stmt.where(Conversation.mode == mode)
    return session.execute(stmt).scalar() or 0


def search(
    session: Session,
    query: str,
    limit: int = 20,
    mode: str | None = None,
) -> list[Conversation]:
    """Case-insensitive substring search. Returns newest-first."""
    stmt = (
        select(Conversation)
        .where(Conversation.content.ilike(f"%{query}%"))
        .order_by(Conversation.id.desc())
        .limit(limit)
    )
    if mode:
        stmt = stmt.where(Conversation.mode == mode)
    return session.exec(stmt).all()
