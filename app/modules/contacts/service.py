"""Contacts domain service: tags, contacts, key dates, warmth maintenance."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import warmth

from .models import Contact, KeyDate, Relationship, Tag
from .schemas import ContactCreate, ContactUpdate, KeyDateIn


# ── Tags ─────────────────────────────────────────────────────────────────────


def get_or_create_tags(db: Session, names: list[str]) -> list[Tag]:
    tags: list[Tag] = []
    for raw in names:
        name = raw.strip()
        if not name:
            continue
        tag = db.scalar(select(Tag).where(Tag.name == name))
        if tag is None:
            tag = Tag(name=name)
            db.add(tag)
            db.flush()
        tags.append(tag)
    return tags


# ── Contacts ─────────────────────────────────────────────────────────────────


def create_contact(db: Session, payload: ContactCreate) -> Contact:
    data = payload.model_dump(exclude={"tags", "key_dates"})
    if data.get("email"):
        data["email"] = str(data["email"])
    contact = Contact(**data)
    contact.tags = get_or_create_tags(db, payload.tags)
    contact.key_dates = [
        KeyDate(date=kd.date, label=kd.label) for kd in payload.key_dates
    ]
    warmth.refresh(contact)
    db.add(contact)
    db.commit()
    db.refresh(contact)
    return contact


def get_contact(db: Session, contact_id: int) -> Contact | None:
    return db.get(Contact, contact_id)


def list_contacts(
    db: Session,
    *,
    search: str | None = None,
    relationship: Relationship | None = None,
    tag: str | None = None,
    sort: str = "warmth",
) -> list[Contact]:
    stmt = select(Contact)
    if relationship is not None:
        stmt = stmt.where(Contact.relationship_type == relationship)
    if search:
        like = f"%{search.lower()}%"
        stmt = stmt.where(
            (Contact.first_name.ilike(like))
            | (Contact.last_name.ilike(like))
            | (Contact.company.ilike(like))
        )
    if tag:
        stmt = stmt.join(Contact.tags).where(Tag.name == tag)

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
    db: Session, contact: Contact, payload: ContactUpdate
) -> Contact:
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


def delete_contact(db: Session, contact: Contact) -> None:
    db.delete(contact)
    db.commit()


# ── Key dates ────────────────────────────────────────────────────────────────


def add_key_date(
    db: Session, contact: Contact, payload: KeyDateIn
) -> KeyDate:
    kd = KeyDate(contact_id=contact.id, date=payload.date, label=payload.label)
    db.add(kd)
    db.commit()
    db.refresh(kd)
    return kd


def delete_key_date(db: Session, key_date: KeyDate) -> None:
    db.delete(key_date)
    db.commit()


# ── Maintenance ──────────────────────────────────────────────────────────────


def refresh_all_warmth(db: Session) -> int:
    contacts = list(db.scalars(select(Contact)))
    for c in contacts:
        warmth.refresh(c)
    db.commit()
    return len(contacts)
