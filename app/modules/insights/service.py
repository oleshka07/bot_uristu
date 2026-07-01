"""Insights domain service: life events."""

from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from app.modules.contacts.models import Contact

from .models import LifeEvent
from .schemas import LifeEventUpdate


def add_life_event(
    db: Session,
    contact: Contact,
    *,
    event_type: str,
    title: str,
    description: str | None = None,
    event_date: date | None = None,
    source: str = "manual",
    suggested_message: str | None = None,
) -> LifeEvent:
    ev = LifeEvent(
        contact_id=contact.id,
        event_type=event_type,
        title=title,
        description=description,
        event_date=event_date,
        source=source,
        suggested_message=suggested_message,
    )
    db.add(ev)
    db.commit()
    db.refresh(ev)
    return ev


def update_life_event(
    db: Session, event: LifeEvent, payload: LifeEventUpdate
) -> LifeEvent:
    if payload.status is not None:
        event.status = payload.status
    if payload.suggested_message is not None:
        event.suggested_message = payload.suggested_message
    db.commit()
    db.refresh(event)
    return event


def get_life_event(db: Session, event_id: int) -> LifeEvent | None:
    return db.get(LifeEvent, event_id)
