"""Settings CRUD operations."""

from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlmodel import Session

from .models import Setting


def get(session: Session, key: str, default: str | None = None) -> str | None:
    row = session.get(Setting, key)
    return row.value if row else default


def set(session: Session, key: str, value: str) -> None:
    stmt = sqlite_insert(Setting).values(key=key, value=value)
    stmt = stmt.on_conflict_do_update(index_elements=["key"], set_={"value": value})
    session.execute(stmt)
    session.commit()
