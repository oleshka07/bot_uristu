"""Reminder service: create, list, and auto-close user-set follow-ups."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.contacts.models import Contact

from .models import Reminder


def create_reminder(
    db: Session, contact: Contact | None, text: str, due_at: datetime
) -> Reminder:
    r = Reminder(
        contact_id=contact.id if contact else None,
        text=text.strip(),
        due_at=due_at,
    )
    db.add(r)
    db.commit()
    db.refresh(r)
    return r


def open_reminders(db: Session) -> list[Reminder]:
    """All not-done reminders, soonest due first."""
    return list(
        db.scalars(
            select(Reminder).where(Reminder.done.is_(False)).order_by(Reminder.due_at)
        )
    )


def due_reminders(db: Session, now: datetime | None = None) -> list[Reminder]:
    """Not-done reminders whose time has come (due_at <= now), oldest first."""
    now = now or datetime.now(timezone.utc)
    return [r for r in open_reminders(db) if _as_utc(r.due_at) <= now]


def complete_for_contact(db: Session, contact_id: int) -> int:
    """Close any open reminders for this contact — the user just reached out,
    so the reminder is fulfilled. Returns how many were closed."""
    if not contact_id:
        return 0
    open_for = [
        r
        for r in open_reminders(db)
        if r.contact_id == contact_id
    ]
    for r in open_for:
        r.done = True
    if open_for:
        db.commit()
    return len(open_for)


def mark_done(db: Session, reminder: Reminder) -> None:
    reminder.done = True
    db.commit()


def _as_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
