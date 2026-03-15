"""Memory CRUD operations."""

from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlmodel import Session, select

from .models import Memory


def save(session: Session, category: str, content: str) -> str:
    """Persist a memory. Returns a status string for the tool result."""
    try:
        stmt = sqlite_insert(Memory).values(category=category, content=content)
        stmt = stmt.on_conflict_do_nothing(index_elements=["content"])
        session.execute(stmt)
        session.commit()
        return "Memory saved."
    except Exception as exc:
        return f"Error: {exc}"


def get_all(session: Session) -> list[Memory]:
    return session.exec(select(Memory).order_by(Memory.created_at)).all()
