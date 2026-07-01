"""Compatibility shim — moved to app.core.database."""
from app.core.database import (  # noqa: F401
    Base,
    SessionLocal,
    engine,
    get_db,
    init_db,
)
