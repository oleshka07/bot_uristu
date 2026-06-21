"""Contact, key-date, interaction and life-event endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import crud, models, schemas
from ..database import get_db

router = APIRouter(prefix="/api", tags=["contacts"])


def _get_contact_or_404(db: Session, contact_id: int) -> models.Contact:
    contact = crud.get_contact(db, contact_id)
    if contact is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Contact not found")
    return contact


# ── Contacts ─────────────────────────────────────────────────────────────────


@router.get("/contacts", response_model=list[schemas.ContactSummary])
def list_contacts(
    search: str | None = None,
    relationship: models.Relationship | None = None,
    tag: str | None = None,
    sort: str = Query("warmth", pattern="^(warmth|name|recent|due)$"),
    db: Session = Depends(get_db),
):
    contacts = crud.list_contacts(
        db, search=search, relationship=relationship, tag=tag, sort=sort
    )
    return [schemas.ContactSummary.from_model(c) for c in contacts]


@router.post(
    "/contacts",
    response_model=schemas.ContactDetail,
    status_code=status.HTTP_201_CREATED,
)
def create_contact(payload: schemas.ContactCreate, db: Session = Depends(get_db)):
    contact = crud.create_contact(db, payload)
    return schemas.ContactDetail.from_model(contact)


@router.get("/contacts/{contact_id}", response_model=schemas.ContactDetail)
def get_contact(contact_id: int, db: Session = Depends(get_db)):
    contact = _get_contact_or_404(db, contact_id)
    return schemas.ContactDetail.from_model(contact)


@router.patch("/contacts/{contact_id}", response_model=schemas.ContactDetail)
def update_contact(
    contact_id: int, payload: schemas.ContactUpdate, db: Session = Depends(get_db)
):
    contact = _get_contact_or_404(db, contact_id)
    contact = crud.update_contact(db, contact, payload)
    return schemas.ContactDetail.from_model(contact)


@router.delete("/contacts/{contact_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_contact(contact_id: int, db: Session = Depends(get_db)):
    contact = _get_contact_or_404(db, contact_id)
    crud.delete_contact(db, contact)


# ── Key dates ────────────────────────────────────────────────────────────────


@router.post(
    "/contacts/{contact_id}/key-dates",
    response_model=schemas.KeyDateOut,
    status_code=status.HTTP_201_CREATED,
)
def add_key_date(
    contact_id: int, payload: schemas.KeyDateIn, db: Session = Depends(get_db)
):
    contact = _get_contact_or_404(db, contact_id)
    return crud.add_key_date(db, contact, payload)


@router.delete(
    "/contacts/{contact_id}/key-dates/{key_date_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_key_date(contact_id: int, key_date_id: int, db: Session = Depends(get_db)):
    kd = db.get(models.KeyDate, key_date_id)
    if kd is None or kd.contact_id != contact_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Key date not found")
    crud.delete_key_date(db, kd)


# ── Interactions ─────────────────────────────────────────────────────────────


@router.post(
    "/contacts/{contact_id}/interactions",
    response_model=schemas.InteractionOut,
    status_code=status.HTTP_201_CREATED,
)
def log_interaction(
    contact_id: int, payload: schemas.InteractionIn, db: Session = Depends(get_db)
):
    contact = _get_contact_or_404(db, contact_id)
    return crud.add_interaction(db, contact, payload)


@router.delete(
    "/contacts/{contact_id}/interactions/{interaction_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_interaction(
    contact_id: int, interaction_id: int, db: Session = Depends(get_db)
):
    itx = db.get(models.Interaction, interaction_id)
    if itx is None or itx.contact_id != contact_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Interaction not found")
    crud.delete_interaction(db, itx)


# ── Life events ──────────────────────────────────────────────────────────────


@router.post(
    "/contacts/{contact_id}/life-events",
    response_model=schemas.LifeEventOut,
    status_code=status.HTTP_201_CREATED,
)
def add_life_event(
    contact_id: int, payload: schemas.LifeEventIn, db: Session = Depends(get_db)
):
    contact = _get_contact_or_404(db, contact_id)
    return crud.add_life_event(
        db,
        contact,
        event_type=payload.event_type,
        title=payload.title,
        description=payload.description,
        event_date=payload.event_date,
        source=payload.source,
    )


@router.patch("/life-events/{event_id}", response_model=schemas.LifeEventOut)
def update_life_event(
    event_id: int, payload: schemas.LifeEventUpdate, db: Session = Depends(get_db)
):
    event = crud.get_life_event(db, event_id)
    if event is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Life event not found")
    return crud.update_life_event(db, event, payload)


# ── Tags ─────────────────────────────────────────────────────────────────────


@router.get("/tags", response_model=list[str])
def list_tags(db: Session = Depends(get_db)):
    return list(db.scalars(select(models.Tag.name).order_by(models.Tag.name)))
