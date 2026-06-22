"""Dashboard and maintenance endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import crud, daily, dashboard, schemas
from ..database import get_db

router = APIRouter(prefix="/api", tags=["dashboard"])


@router.get("/dashboard", response_model=schemas.Dashboard)
def get_dashboard(db: Session = Depends(get_db)):
    return dashboard.build_dashboard(db)


@router.post("/maintenance/refresh-warmth")
def refresh_warmth(db: Session = Depends(get_db)):
    count = crud.refresh_all_warmth(db)
    return {"refreshed": count}


@router.post("/maintenance/run-daily")
def run_daily(send_digest: bool = False):
    """Trigger the daily job on demand (warmth refresh + Google sync, and
    optionally send the digest email)."""
    return daily.run_daily_job(send_digest=send_digest)
