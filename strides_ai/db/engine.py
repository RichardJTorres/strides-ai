"""Database engine, session dependency, and migrations."""

from pathlib import Path
from typing import Generator

import sqlalchemy as sa
from sqlmodel import Session, create_engine

DB_PATH = Path.home() / ".strides_ai" / "activities.db"

_engine: sa.engine.Engine | None = None


def get_engine() -> sa.engine.Engine:
    global _engine
    if _engine is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _engine = create_engine(
            f"sqlite:///{DB_PATH}",
            connect_args={"check_same_thread": False},
        )
    return _engine


def reset_engine() -> None:
    global _engine
    if _engine is not None:
        _engine.dispose()
        _engine = None


def get_session() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a request-scoped SQLModel session."""
    with Session(get_engine()) as session:
        yield session


def _make_alembic_config():
    from alembic.config import Config

    alembic_dir = Path(__file__).parent.parent.parent / "alembic"
    cfg = Config()
    cfg.set_main_option("script_location", str(alembic_dir))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{DB_PATH}")
    return cfg


def init_db() -> None:
    reset_engine()
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    from alembic import command as alembic_command

    cfg = _make_alembic_config()

    with get_engine().connect() as conn:
        tables = (
            conn.execute(sa.text("SELECT name FROM sqlite_master WHERE type='table'"))
            .scalars()
            .all()
        )

    if "activities" in tables and "alembic_version" not in tables:
        alembic_command.stamp(cfg, "head")
    else:
        alembic_command.upgrade(cfg, "head")
