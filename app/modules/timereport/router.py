"""Time-report API — the PC agent's endpoints (behind the global X-API-Key).

  GET  /api/timereport/poll     → is there a pending request? (claims it)
  POST /api/timereport/deliver  → here's the raw report; analyse + send it
"""

from __future__ import annotations

import html

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db

from . import service

router = APIRouter(prefix="/api/timereport", tags=["timereport"])


class DailyIn(BaseModel):
    date: str
    payload: dict


class DeliverIn(BaseModel):
    markdown: str
    request_id: int | None = None
    period: str = "week"


def _chunks(text: str, size: int = 3500):
    for i in range(0, len(text), size):
        yield text[i : i + size]


@router.get("/poll")
def poll(db: Session = Depends(get_db)):
    req = service.claim_pending(db)
    return {
        "pending": req is not None,
        "request_id": req.id if req else None,
        "period": req.period if req else None,
    }


@router.post("/daily")
def daily(body: DailyIn, db: Session = Depends(get_db)):
    """Агент з ПК шле денний зріз (о 20:00 і о 22:00). Тут лише зберігаємо."""
    from datetime import date

    service.save_snapshot(db, date.fromisoformat(body.date), body.payload)
    return {"ok": True}


@router.get("/daily/preview")
def daily_preview(db: Session = Depends(get_db)):
    """Подивитись, яким буде вечірнє зведення (без надсилання)."""
    return {"text": service.daily_digest(db)}


@router.post("/deliver")
def deliver(payload: DeliverIn, db: Session = Depends(get_db)):
    from app.modules.automation import telegram
    from app.modules.goals.service import active_goals
    from app.modules.insights import ai

    md = (payload.markdown or "").strip()
    if not md:
        return {"ok": False, "error": "empty report"}

    goals = [g.title for g in active_goals(db)]
    analysis = ai.analyze_time_report(md, goals)

    sent = False
    if analysis:
        body = "📊 <b>Тижневий трекінг — аналіз</b>\n\n" + html.escape(analysis)
        sent = telegram.send_message(body) or sent
    else:
        sent = telegram.send_message(
            "📊 <b>Тижневий трекінг</b>\n\n"
            "AI-аналіз недоступний — надсилаю сирий звіт."
        ) or sent

    # A compact excerpt of the raw report for the numbers (kept short).
    excerpt = md if len(md) <= 3500 else md[:3500].rsplit("\n", 1)[0] + "\n…"
    sent = telegram.send_message(
        "<b>Деталі</b>\n<pre>" + html.escape(excerpt) + "</pre>"
    ) or sent

    service.mark_delivered(db, payload.request_id)
    return {"ok": True, "sent": sent, "goals_considered": len(goals)}
