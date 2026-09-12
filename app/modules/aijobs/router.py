"""Панель фонового AI: режим, черга, використання, пауза."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.core.database import get_db

from . import service

router = APIRouter(prefix="/api/aijobs", tags=["aijobs"])


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    kind: str
    status: str
    attempts: int
    backend: str | None
    created_at: datetime
    finished_at: datetime | None
    result: str | None
    error: str | None


@router.get("/status")
def status(db: Session = Depends(get_db)):
    return service.stats(db)


@router.get("", response_model=list[JobOut])
def recent(db: Session = Depends(get_db)):
    return service.recent(db)


@router.post("/pause")
def pause(db: Session = Depends(get_db)):
    service.set_paused(db, True)
    return service.stats(db)


@router.post("/resume")
def resume(db: Session = Depends(get_db)):
    service.set_paused(db, False)
    return service.stats(db)
