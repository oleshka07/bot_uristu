"""Dashboard and maintenance endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import crud, dashboard, schemas
from ..database import get_db

router = APIRouter(prefix="/api", tags=["dashboard"])


@router.get("/dashboard", response_model=schemas.Dashboard)
def get_dashboard(db: Session = Depends(get_db)):
    return dashboard.build_dashboard(db)


@router.post("/maintenance/refresh-warmth")
def refresh_warmth(db: Session = Depends(get_db)):
    count = crud.refresh_all_warmth(db)
    return {"refreshed": count}
