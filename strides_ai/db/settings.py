"""Settings CRUD operations."""

from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlmodel import Session

from ..units import DEFAULT_UNIT_SYSTEM, UnitSystem
from .models import Setting

UNIT_SYSTEM_KEY = "unit_system"


def get(session: Session, key: str, default: str | None = None) -> str | None:
    row = session.get(Setting, key)
    return row.value if row else default


def set(session: Session, key: str, value: str) -> None:
    stmt = sqlite_insert(Setting).values(key=key, value=value)
    stmt = stmt.on_conflict_do_update(index_elements=["key"], set_={"value": value})
    session.execute(stmt)
    session.commit()


def get_unit_system(session: Session) -> UnitSystem:
    """The athlete's display unit system. Every measurement is stored in SI; this only
    controls how values are shown and what units the coach is told to use."""
    return UnitSystem.parse(get(session, UNIT_SYSTEM_KEY, DEFAULT_UNIT_SYSTEM.value))
