"""API коуча: зріз для сторінки, налаштування, журнал, питання на вимогу."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db

from . import service
from .models import Checkin
from .schemas import AskResult, BoardOut, CheckinOut, SettingsOut, SettingsUpdate

router = APIRouter(prefix="/api/coach", tags=["coach"])


@router.get("/board", response_model=BoardOut)
def get_board(db: Session = Depends(get_db)):
    return service.board(db)


@router.get("/settings", response_model=SettingsOut)
def get_settings(db: Session = Depends(get_db)):
    return service.get_settings(db)


@router.patch("/settings", response_model=SettingsOut)
def update_settings(payload: SettingsUpdate, db: Session = Depends(get_db)):
    row = service.get_settings(db)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(row, field, value)
    db.commit()
    db.refresh(row)
    return row


@router.get("/checkins", response_model=list[CheckinOut])
def list_checkins(
    goal_id: int | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    stmt = select(Checkin).order_by(Checkin.asked_at.desc()).limit(limit)
    if goal_id is not None:
        stmt = stmt.where(Checkin.goal_id == goal_id)
    return list(db.scalars(stmt))


@router.post("/ask", response_model=AskResult)
def ask_now(db: Session = Depends(get_db)):
    """Задає питання просто зараз — та сама логіка, що й о 16:00."""
    from .jobs import _configured, _esc

    opened = service.open_question(db, force=True)
    if opened is None:
        return AskResult(asked=False, reason="Немає активних цілей")
    checkin, question = opened
    if _configured():
        from app.modules.automation import telegram

        telegram.send_message(_esc(question))
    return AskResult(asked=True, question=question, goal_id=checkin.goal_id)
