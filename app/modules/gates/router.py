"""API воріт: створити з коду, забрати відкриті, закрити, пінгнути."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db

from . import service
from .schemas import GateIn, GateNudge, GateOut

router = APIRouter(prefix="/api/gates", tags=["gates"])


def _out(db: Session, task) -> GateOut:
    return GateOut(
        uid=task.uid,
        text=task.title,
        created_at=task.created_at,
        age_hours=int(service.age_hours(task)),
        goal=service.goal_title(db, task),
        project=task.project,
    )


@router.get("", response_model=list[GateOut])
def list_gates(db: Session = Depends(get_db)):
    return [_out(db, t) for t in service.open_gates(db)]


@router.post("", response_model=GateOut, status_code=status.HTTP_201_CREATED)
def create_gate(payload: GateIn, db: Session = Depends(get_db)):
    """Заводить ворота і одразу штовхає їх у Telegram — щоб не загубилися."""
    task = service.create_gate(
        db,
        text=payload.text,
        goal_hint=payload.goal,
        goal_id=payload.goal_id,
        project=payload.project,
    )
    from app.core.config import settings

    if settings.telegram_bot_token and settings.telegram_chat_id:
        import html

        from app.modules.automation import telegram

        goal = service.goal_title(db, task)
        tail = f"\nБлокує: {html.escape(goal)}." if goal else ""
        telegram.send_message(f"Ворота: {html.escape(task.title)}{tail}")
    return _out(db, task)


@router.post("/{uid}/done", response_model=GateOut)
def close_gate(uid: str, db: Session = Depends(get_db)):
    task = service.close_gate(db, uid)
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Gate not found")
    return _out(db, task)


@router.post("/nudge", response_model=GateNudge)
def nudge(db: Session = Depends(get_db)):
    """Пінг у Telegram про ворота, що висять понад добу (не частіше разу на 6 год)."""
    text = service.nudge(db)
    if not text:
        return GateNudge(sent=False)
    from app.core.config import settings

    if settings.telegram_bot_token and settings.telegram_chat_id:
        import html

        from app.modules.automation import telegram

        telegram.send_message(html.escape(text))
    return GateNudge(sent=True, text=text)
