"""Insights domain service: life events + stable contact facts."""

from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.contacts.models import Contact

from .models import ContactFact, FactType, LifeEvent
from .schemas import ContactFactUpdate, LifeEventUpdate

# Fact types that hold a single current value — a new one supersedes the old.
SINGLE_VALUED = {FactType.role, FactType.employer, FactType.location}


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


# ── Contact facts ────────────────────────────────────────────────────────────


def current_facts(db: Session, contact_id: int) -> list[ContactFact]:
    """All facts that are still current (not superseded / not expired)."""
    facts = db.scalars(
        select(ContactFact)
        .where(ContactFact.contact_id == contact_id)
        .order_by(ContactFact.fact_type, ContactFact.created_at.desc())
    )
    return [f for f in facts if f.is_current]


def get_fact(db: Session, fact_id: int) -> ContactFact | None:
    return db.get(ContactFact, fact_id)


def add_fact(
    db: Session,
    contact: Contact,
    *,
    fact_type: FactType,
    value: str,
    valid_from: date | None = None,
    valid_to: date | None = None,
    confidence: float = 0.7,
    source: str = "manual",
    source_ref: str | None = None,
) -> ContactFact:
    """Record a fact with non-destructive supersession.

    * If an identical current fact of the same type already exists, it is
      returned unchanged (idempotent — safe for re-running AI extraction).
    * For single-valued types (role/employer/location) any other current fact
      of that type is invalidated so only the newest one stays current.
    """
    normalized = value.strip()
    existing_current = [
        f
        for f in contact.facts
        if f.fact_type == fact_type and f.is_current
    ]

    for f in existing_current:
        if f.value.strip().casefold() == normalized.casefold():
            return f  # already known — no duplicate

    if fact_type in SINGLE_VALUED:
        now = datetime.now(timezone.utc)
        for f in existing_current:
            f.invalid_at = now

    fact = ContactFact(
        contact_id=contact.id,
        fact_type=fact_type,
        value=normalized,
        valid_from=valid_from,
        valid_to=valid_to,
        confidence=confidence,
        source=source,
        source_ref=source_ref,
    )
    db.add(fact)
    db.commit()
    db.refresh(fact)
    return fact


def update_fact(
    db: Session, fact: ContactFact, payload: ContactFactUpdate
) -> ContactFact:
    if payload.value is not None:
        fact.value = payload.value.strip()
    if payload.fact_type is not None:
        fact.fact_type = payload.fact_type
    if payload.valid_to is not None:
        fact.valid_to = payload.valid_to
    if payload.confidence is not None:
        fact.confidence = payload.confidence
    db.commit()
    db.refresh(fact)
    return fact


def invalidate_fact(db: Session, fact: ContactFact) -> ContactFact:
    """Mark a fact as no longer true (kept for history, not deleted)."""
    if fact.invalid_at is None:
        fact.invalid_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(fact)
    return fact
