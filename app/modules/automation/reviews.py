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


# ── Relationship reflection (Mesh: "Reflect on your relationship with…") ──────


def _reflection_context(db, contact) -> str:
    """Compact digest for one contact, for the reflection prompt."""
    from app import warmth
    from app.modules.automation import reminders as _reminders

    parts = [f"Ім'я: {contact.full_name}"]
    role = " · ".join(filter(None, [contact.position, contact.company]))
    if role:
        parts.append(f"Роль: {role}")
    parts.append(
        f"Теплота: {contact.warmth_status}; "
        f"{round(warmth.days_since_last_contact(contact))} дн. без контакту; "
        f"ціль: {contact.contact_frequency.value}"
    )
    facts = [f.value for f in getattr(contact, "facts", []) if f.is_current][:5]
    if facts:
        parts.append("Факти: " + "; ".join(facts))
    itx = sorted(contact.interactions, key=lambda i: i.occurred_at)
    if itx and itx[-1].summary:
        parts.append(f"Остання взаємодія: {itx[-1].summary[:150]}")
    open_r = [
        r for r in _reminders.open_reminders(db) if r.contact_id == contact.id
    ]
    if open_r:
        parts.append("Відкриті нагадування: " + "; ".join(r.text for r in open_r[:3]))
    return "\n".join(parts)


def pick_reflection_contacts(db, n: int) -> list:
    """The relationships most worth a deliberate think: important people who
    are drifting (overdue / cooling), best-known first."""
    from app import warmth
    from app.modules.contacts.models import Contact
    from app.modules.telegram_bot.service import effective_importance
    from sqlalchemy import select

    contacts = [
        c
        for c in db.scalars(select(Contact)).unique()
        if not c.do_not_contact and c.interactions
    ]
    drifting = [
        c
        for c in contacts
        if warmth.is_due(c) or c.warmth_status in ("cooling", "cold")
    ]
    pool = drifting or contacts
    pool.sort(
        key=lambda c: (effective_importance(c), warmth.overdue_ratio(c)),
        reverse=True,
    )
    return pool[:n]


def reflection_text(db, contacts) -> str | None:
    """AI reflection + next action for each contact. None if AI unavailable
    or nothing to reflect on."""
    from app.modules.insights import ai

    if not contacts:
        return None
    items = [{"id": c.id, "context": _reflection_context(db, c)} for c in contacts]
    reflections = ai.reflect_on_relationships(items)
    if not reflections:
        return None
    by_id = {c.id: c for c in contacts}
    lines = ["🪞 <b>Подумай про стосунки</b>"]
    for r in reflections:
        c = by_id.get(r.get("contact_id"))
        if c is None:
            continue
        lines.append("")
        lines.append(f"👤 <b>{_esc(c.full_name)}</b>")
        if r.get("reflection"):
            lines.append(_esc(r["reflection"]))
        if r.get("action"):
            lines.append(f"➡️ <i>{_esc(r['action'])}</i>")
    return "\n".join(lines) if len(lines) > 1 else None


def run_weekly_reflection() -> bool:
    if not (settings.reflection_enabled and _configured()):
        return False
    from app.modules.automation import telegram

    with SessionLocal() as db:
        contacts = pick_reflection_contacts(db, settings.reflection_count)
        text = reflection_text(db, contacts)
    if not text:
        return False
    return telegram.send_message(text, reply_markup=_QUEUE_BUTTON)
