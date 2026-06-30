"""In-memory log ring buffer + diagnostics snapshot.

Gives the app a way to expose its own recent logs and state over the API, so
the running service can be inspected without shell access to the server.
"""

from __future__ import annotations

import collections
import logging
from datetime import datetime, timezone

_BUFFER: collections.deque[dict] = collections.deque(maxlen=1000)


class RingBufferHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = record.getMessage()
        except Exception:
            message = str(record.msg)
        _BUFFER.append(
            {
                "time": datetime.fromtimestamp(record.created, tz=timezone.utc)
                .isoformat()
                .replace("+00:00", "Z"),
                "level": record.levelname,
                "logger": record.name,
                "message": message[:2000],
            }
        )


def install() -> None:
    """Attach the ring-buffer handler to the root logger (idempotent)."""
    root = logging.getLogger()
    if any(isinstance(h, RingBufferHandler) for h in root.handlers):
        return
    handler = RingBufferHandler()
    handler.setLevel(logging.INFO)
    root.addHandler(handler)


def recent(limit: int = 200, level: str | None = None) -> list[dict]:
    items = list(_BUFFER)
    if level:
        wanted = level.upper()
        items = [x for x in items if x["level"] == wanted]
    return items[-limit:]


def snapshot(db) -> dict:
    """A one-call health picture of the service and its integrations."""
    from sqlalchemy import func, select

    from . import __version__, models, warmth
    from .config import settings
    from .integrations import chater, google

    try:
        contacts = db.scalar(select(func.count()).select_from(models.Contact)) or 0
        interactions = (
            db.scalar(select(func.count()).select_from(models.Interaction)) or 0
        )
        due = sum(1 for c in db.scalars(select(models.Contact)) if warmth.is_due(c))
        db_info = {"contacts": contacts, "interactions": interactions, "due": due}
    except Exception as exc:
        db_info = {"error": str(exc)}

    try:
        g_status = google.status(db)
    except Exception as exc:
        g_status = {"error": str(exc)}

    errors = recent(limit=25, level="ERROR") + recent(limit=25, level="WARNING")
    errors.sort(key=lambda x: x["time"])

    return {
        "version": __version__,
        "time": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "ai_enabled": settings.ai_enabled,
        "auth_enabled": settings.auth_enabled,
        "scheduler_enabled": settings.scheduler_enabled,
        "database": db_info,
        "integrations": {
            "google": g_status,
            "chater": {**chater.status(), "contacts": chater.duplicate_count(db)},
            "telegram": {"configured": settings.telegram_configured},
        },
        "recent_warnings_errors": errors[-25:],
    }
