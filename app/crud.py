"""Database operations (CRUD) for contacts and related entities."""

from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models, schemas, warmth


# ── Tags ─────────────────────────────────────────────────────────────────────


def get_or_create_tags(db: Session, names: list[str]) -> list[models.Tag]:
    tags: list[models.Tag] = []
    for raw in names:
        name = raw.strip()
        if not name:
            continue
        tag = db.scalar(select(models.Tag).where(models.Tag.name == name))
        if tag is None:
            tag = models.Tag(name=name)
            db.add(tag)
            db.flush()
        tags.append(tag)
    return tags


# ── Contacts ─────────────────────────────────────────────────────────────────


def create_contact(db: Session, payload: schemas.ContactCreate) -> models.Contact:
    data = payload.model_dump(exclude={"tags", "key_dates"})
    if data.get("email"):
        data["email"] = str(data["email"])
    contact = models.Contact(**data)
    contact.tags = get_or_create_tags(db, payload.tags)
    contact.key_dates = [
        models.KeyDate(date=kd.date, label=kd.label) for kd in payload.key_dates
    ]
    warmth.refresh(contact)
    db.add(contact)
    db.commit()
    db.refresh(contact)
    return contact


def get_contact(db: Session, contact_id: int) -> models.Contact | None:
    return db.get(models.Contact, contact_id)


def list_contacts(
    db: Session,
    *,
    search: str | None = None,
    relationship: models.Relationship | None = None,
    tag: str | None = None,
    sort: str = "warmth",
) -> list[models.Contact]:
    stmt = select(models.Contact)
    if relationship is not None:
        stmt = stmt.where(models.Contact.relationship_type == relationship)
    if search:
        like = f"%{search.lower()}%"
        stmt = stmt.where(
            (models.Contact.first_name.ilike(like))
            | (models.Contact.last_name.ilike(like))
            | (models.Contact.company.ilike(like))
        )
    if tag:
        stmt = stmt.join(models.Contact.tags).where(models.Tag.name == tag)

    contacts = list(db.scalars(stmt).unique())

    if sort == "name":
        contacts.sort(key=lambda c: c.full_name.lower())
    elif sort == "recent":
        contacts.sort(
            key=lambda c: c.last_contacted_at or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )
    elif sort == "due":
        contacts.sort(key=warmth.overdue_ratio, reverse=True)
    else:  # warmth (coldest first — those needing attention)
        contacts.sort(key=lambda c: c.warmth_score)
    return contacts


def update_contact(
    db: Session, contact: models.Contact, payload: schemas.ContactUpdate
) -> models.Contact:
    data = payload.model_dump(exclude_unset=True, exclude={"tags"})
    if "email" in data and data["email"] is not None:
        data["email"] = str(data["email"])
    for field, value in data.items():
        setattr(contact, field, value)
    if payload.tags is not None:
        contact.tags = get_or_create_tags(db, payload.tags)
    warmth.refresh(contact)
    db.commit()
    db.refresh(contact)
    return contact


def delete_contact(db: Session, contact: models.Contact) -> None:
    db.delete(contact)
    db.commit()


# ── Key dates ────────────────────────────────────────────────────────────────


def add_key_date(
    db: Session, contact: models.Contact, payload: schemas.KeyDateIn
) -> models.KeyDate:
    kd = models.KeyDate(contact_id=contact.id, date=payload.date, label=payload.label)
    db.add(kd)
    db.commit()
    db.refresh(kd)
    return kd


def delete_key_date(db: Session, key_date: models.KeyDate) -> None:
    db.delete(key_date)
    db.commit()


# ── Interactions ─────────────────────────────────────────────────────────────


def add_interaction(
    db: Session, contact: models.Contact, payload: schemas.InteractionIn
) -> models.Interaction:
    occurred = payload.occurred_at or datetime.now(timezone.utc)
    itx = models.Interaction(
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
            select(models.Interaction.id).where(
                models.Interaction.contact_id == contact_id,
                models.Interaction.external_id == external_id,
            )
        )
        is not None
    )


def add_synced_interaction(
    db: Session,
    contact: models.Contact,
    *,
    occurred_at: datetime,
    channel: models.Channel,
    direction: models.Direction,
    summary: str | None,
    source: str,
    external_id: str,
    sentiment: float = 0.0,
) -> models.Interaction:
    """Insert an interaction from an external feed. Warmth is *not* refreshed
    here — the caller refreshes once after a batch for efficiency. The caller
    must ensure the external_id is not already present."""
    itx = models.Interaction(
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


def delete_interaction(db: Session, interaction: models.Interaction) -> None:
    contact = interaction.contact
    db.delete(interaction)
    db.flush()
    db.refresh(contact)
    warmth.refresh(contact)
    db.commit()


# ── Life events ──────────────────────────────────────────────────────────────


def add_life_event(
    db: Session,
    contact: models.Contact,
    *,
    event_type: str,
    title: str,
    description: str | None = None,
    event_date: date | None = None,
    source: str = "manual",
    suggested_message: str | None = None,
) -> models.LifeEvent:
    ev = models.LifeEvent(
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
    db: Session, event: models.LifeEvent, payload: schemas.LifeEventUpdate
) -> models.LifeEvent:
    if payload.status is not None:
        event.status = payload.status
    if payload.suggested_message is not None:
        event.suggested_message = payload.suggested_message
    db.commit()
    db.refresh(event)
    return event


def get_life_event(db: Session, event_id: int) -> models.LifeEvent | None:
    return db.get(models.LifeEvent, event_id)


# ── Social snapshots ─────────────────────────────────────────────────────────


def upsert_snapshot(
    db: Session,
    contact: models.Contact,
    *,
    platform: str,
    url: str,
    title: str | None,
    raw_text: str | None,
) -> models.SocialSnapshot:
    existing = db.scalar(
        select(models.SocialSnapshot).where(
            models.SocialSnapshot.contact_id == contact.id,
            models.SocialSnapshot.url == url,
        )
    )
    if existing:
        existing.platform = platform
        existing.title = title
        existing.raw_text = raw_text
        existing.fetched_at = datetime.now(timezone.utc)
        snapshot = existing
    else:
        snapshot = models.SocialSnapshot(
            contact_id=contact.id,
            platform=platform,
            url=url,
            title=title,
            raw_text=raw_text,
        )
        db.add(snapshot)
    db.commit()
    db.refresh(snapshot)
    return snapshot


# ── Maintenance ──────────────────────────────────────────────────────────────


def refresh_all_warmth(db: Session) -> int:
    contacts = list(db.scalars(select(models.Contact)))
    for c in contacts:
        warmth.refresh(c)
    db.commit()
    return len(contacts)
