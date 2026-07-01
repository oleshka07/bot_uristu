"""Interactions domain service: recording and syncing interactions."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import warmth
from app.modules.contacts.models import Contact

from .models import Channel, Direction, Interaction
from .schemas import InteractionIn


def add_interaction(
    db: Session, contact: Contact, payload: InteractionIn
) -> Interaction:
    occurred = payload.occurred_at or datetime.now(timezone.utc)
    itx = Interaction(
        contact_id=contact.id,
        occurred_at=occurred,
        channel=payload.channel,
        direction=payload.direction,
        sentiment=payload.sentiment,
        summary=payload.summary,
    )
    db.add(itx)
    db.flush()
    db.refresh(contact)
    warmth.refresh(contact)
    db.commit()
    db.refresh(itx)
    return itx


def interaction_exists(db: Session, contact_id: int, external_id: str) -> bool:
    return (
        db.scalar(
            select(Interaction.id).where(
                Interaction.contact_id == contact_id,
                Interaction.external_id == external_id,
            )
        )
        is not None
    )


def add_synced_interaction(
    db: Session,
    contact: Contact,
    *,
    occurred_at: datetime,
    channel: Channel,
    direction: Direction,
    summary: str | None,
    source: str,
    external_id: str,
    sentiment: float = 0.0,
) -> Interaction:
    """Insert an interaction from an external feed. Warmth is *not* refreshed
    here — the caller refreshes once after a batch for efficiency. The caller
    must ensure the external_id is not already present."""
    itx = Interaction(
        contact_id=contact.id,
        occurred_at=occurred_at,
        channel=channel,
        direction=direction,
        sentiment=sentiment,
        summary=summary,
        source=source,
        external_id=external_id,
    )
    db.add(itx)
    db.flush()
    return itx


def delete_interaction(db: Session, interaction: Interaction) -> None:
    contact = interaction.contact
    db.delete(interaction)
    db.flush()
    db.refresh(contact)
    warmth.refresh(contact)
    db.commit()
