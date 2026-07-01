"""Database engine, session factory and declarative base."""

from __future__ import annotations

from collections.abc import Generator
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings


def utcnow() -> datetime:
    """Timezone-aware UTC now — shared default for model timestamp columns."""
    return datetime.now(timezone.utc)

# SQLite needs a special flag for multithreaded use (uvicorn workers/threads).
connect_args = {}
if settings.database_url.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(
    settings.database_url,
    connect_args=connect_args,
    pool_pre_ping=True,
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a scoped database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create all tables, then reconcile columns added in later versions."""
    from app.core import registry  # noqa: F401  (registers every ORM model)
    from .migrations import ensure_schema

    Base.metadata.create_all(bind=engine)
    ensure_schema(engine)
