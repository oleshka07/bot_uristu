"""Admin / diagnostics endpoints (auth-protected).

Exposes the service's own state and recent logs so it can be inspected over the
API without shell access. Protected by the global auth middleware (Basic or
X-API-Key) when APP_PASSWORD is set.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app import diagnostics
from app.core.database import get_db

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/diagnostics")
def get_diagnostics(db: Session = Depends(get_db)):
    return diagnostics.snapshot(db)


@router.get("/logs")
def get_logs(
    limit: int = Query(default=200, ge=1, le=1000),
    level: str | None = Query(default=None),
):
    return {"logs": diagnostics.recent(limit=limit, level=level)}
