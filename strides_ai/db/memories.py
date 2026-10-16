"""Memory CRUD operations."""

from datetime import date

from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlmodel import Session, select

from .models import Memory
from ..memory_context import MemoryTiming


def save(session: Session, category: str, content: str, **metadata) -> str:
    """Save a fact or explicitly revise its content and timing."""
    try:
        memory_id = metadata.pop("memory_id", None)
        if not content.strip():
            return "Error: Memory content cannot be empty."
        if memory_id is not None:
            memory = update(session, memory_id, category, content.strip(), **metadata)
            return "Memory updated." if memory else "Error: Memory not found."
        metadata.setdefault("effective_from", date.today().isoformat())
        timing = MemoryTiming(**metadata).model_dump(mode="json")
        stmt = sqlite_insert(Memory).values(category=category, content=content.strip(), **timing)
        stmt = stmt.on_conflict_do_nothing(index_elements=["content"])
        session.execute(stmt)
        session.commit()
        return "Memory saved."
    except Exception as exc:
        session.rollback()
        return f"Error: {exc}"


def get_all(session: Session) -> list[Memory]:
    return session.exec(select(Memory).order_by(Memory.created_at)).all()


def update(
    session: Session, memory_id: int, category: str, content: str, **metadata
) -> Memory | None:
    memory = session.get(Memory, memory_id)
    if memory is None:
        return None
    timing = MemoryTiming(
        **{**{k: getattr(memory, k) for k in MemoryTiming.model_fields}, **metadata}
    )
    for key, value in timing.model_dump(mode="json").items():
        setattr(memory, key, value)
    memory.category = category
    memory.content = content
    session.add(memory)
    session.commit()
    session.refresh(memory)
    return memory


def delete(session: Session, memory_id: int) -> bool:
    memory = session.get(Memory, memory_id)
    if memory is None:
        return False
    session.delete(memory)
    session.commit()
    return True
