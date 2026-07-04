"""Proactive check-ins and reviews pushed to Telegram.

- Midday check-in: a short nudge — who's due, follow-ups waiting, top goal.
  Silence-aware: skipped when there's nothing actionable.
- Weekly review (Mondays): network pulse — reached-out count, still-due,
  goals progress — so the week starts with a plan.

Runs in the web process scheduler; sends via the automation Telegram helper.
"""

from __future__ import annotations

import html
import logging
from datetime import datetime, timedelta, timezone

from app.core.config import settings
from app.core.database import SessionLocal

logger = logging.getLogger("networking.reviews")


def _esc(s: str) -> str:
    return html.escape(str(s))


def _configured() -> bool:
    return bool(settings.telegram_bot_token and settings.telegram_chat_id)


def _active_goals(db):
    from app.modules.goals.models import GoalStatus
    from app.modules.goals.service import list_goals

    return list_goals(db, status=GoalStatus.active)


def _reached_out_since(db, days: int) -> int:
    from sqlalchemy import func, select

    from app.modules.interactions.models import Direction, Interaction

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    return db.scalar(
        select(func.count(Interaction.id)).where(
            Interaction.direction == Direction.outbound,
            Interaction.source == "telegram",
            Interaction.occurred_at >= cutoff,
        )
    ) or 0


def midday_checkin_text(db) -> str | None:
    """Short nudge; None when nothing worth pinging about (silence-aware)."""
    from app.modules.dashboard.service import build_dashboard

    data = build_dashboard(db)
    due = data.stats.due_now
    events = len(data.pending_events)
    goals = _active_goals(db)
    if settings.digest_quiet_when_empty and not due and not events:
        return None

    lines = ["☀️ <b>Полуденний чек-ін</b>"]
    if due:
        top = ", ".join(_esc(s.contact.full_name) for s in data.suggestions[:3])
        lines.append(f"📇 Прострочених: <b>{due}</b>" + (f" — напр. {top}" if top else ""))
    if events:
        lines.append(f"🎉 Нових подій: <b>{events}</b>")
    if goals:
        lines.append(f"🎯 Активних цілей: {len(goals)}")
    lines.append("\nНатисни /queue — почнемо обхід.")
    return "\n".join(lines)


def weekly_review_text(db) -> str:
    from app.modules.dashboard.service import build_dashboard

    data = build_dashboard(db)
    s = data.stats
    reached = _reached_out_since(db, 7)
    goals = _active_goals(db)

    lines = [
        "📊 <b>Тижневий огляд мережі</b>",
        f"Контактів: {s.total_contacts} · середня теплота: {s.average_warmth}",
        f"За тиждень написав: <b>{reached}</b> · прострочено зараз: <b>{s.due_now}</b>",
    ]
    if goals:
        lines.append("\n🎯 <b>Цілі</b>")
        for g in goals[:5]:
            lines.append(f"• {_esc(g.title)} — {len(g.contacts)} причетних")
    if data.suggestions:
        lines.append("\n<b>Почни тиждень із цих людей:</b>")
        for sg in data.suggestions[:5]:
            lines.append(f"• {_esc(sg.contact.full_name)} — {_esc(sg.reason)}")
    lines.append("\n/queue — обхід на сьогодні.")
    return "\n".join(lines)


_QUEUE_BUTTON = {
    "inline_keyboard": [[{"text": "🚀 Почати обхід", "callback_data": "q:start"}]]
}


def run_midday_checkin() -> bool:
    if not (settings.checkin_enabled and _configured()):
        return False
    from app.modules.automation import telegram

    with SessionLocal() as db:
        text = midday_checkin_text(db)
    if not text:
        return False
    return telegram.send_message(text, reply_markup=_QUEUE_BUTTON)


def run_weekly_review() -> bool:
    if not (settings.weekly_review_enabled and _configured()):
        return False
    from app.modules.automation import telegram

    with SessionLocal() as db:
        text = weekly_review_text(db)
    return telegram.send_message(text, reply_markup=_QUEUE_BUTTON)
