"""AI endpoints: dossiers, outreach recommendations and event messages."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app import ai, crud, schemas
from app.core.config import settings
from app.core.database import get_db
from app.modules.insights import service as insights_service
from app.modules.insights.schemas import (
    ContactFactIn,
    ContactFactOut,
    ContactFactUpdate,
)

router = APIRouter(prefix="/api", tags=["ai"])


def _get_contact_or_404(db: Session, contact_id: int):
    contact = crud.get_contact(db, contact_id)
    if contact is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Contact not found")
    return contact


def _get_fact_or_404(db: Session, fact_id: int):
    fact = insights_service.get_fact(db, fact_id)
    if fact is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Fact not found")
    return fact


@router.get("/ai/status")
def ai_status():
    return {"ai_enabled": settings.ai_enabled, "model": settings.ai_model}


@router.post("/contacts/{contact_id}/dossier", response_model=schemas.ContactDetail)
def generate_dossier(contact_id: int, db: Session = Depends(get_db)):
    contact = crud.get_contact(db, contact_id)
    if contact is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Contact not found")
    contact.ai_dossier = ai.generate_dossier(contact)
    contact.ai_dossier_updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(contact)
    return schemas.ContactDetail.from_model(contact)


@router.get(
    "/contacts/{contact_id}/recommendation",
    response_model=schemas.OutreachRecommendation,
)
def get_recommendation(contact_id: int, db: Session = Depends(get_db)):
    contact = crud.get_contact(db, contact_id)
    if contact is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Contact not found")
    return ai.recommend_outreach(contact)


@router.post("/life-events/{event_id}/message")
def generate_event_message(event_id: int, db: Session = Depends(get_db)):
    event = crud.get_life_event(db, event_id)
    if event is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Life event not found")
    message = ai.suggest_event_message(event.contact, event)
    event.suggested_message = message
    db.commit()
    return {"message": message}


# ── Contact facts (stable knowledge with validity windows) ───────────────────


@router.get(
    "/contacts/{contact_id}/facts", response_model=list[ContactFactOut]
)
def list_facts(
    contact_id: int,
    include_history: bool = Query(default=False),
    db: Session = Depends(get_db),
):
    contact = _get_contact_or_404(db, contact_id)
    if include_history:
        return list(contact.facts)
    return insights_service.current_facts(db, contact_id)


@router.post(
    "/contacts/{contact_id}/facts",
    response_model=ContactFactOut,
    status_code=status.HTTP_201_CREATED,
)
def add_fact(
    contact_id: int, payload: ContactFactIn, db: Session = Depends(get_db)
):
    contact = _get_contact_or_404(db, contact_id)
    return insights_service.add_fact(
        db,
        contact,
        fact_type=payload.fact_type,
        value=payload.value,
        valid_from=payload.valid_from,
        valid_to=payload.valid_to,
        confidence=payload.confidence,
        source=payload.source,
        source_ref=payload.source_ref,
    )


@router.post(
    "/contacts/{contact_id}/facts/extract",
    response_model=list[ContactFactOut],
)
def extract_facts(contact_id: int, db: Session = Depends(get_db)):
    """Read the contact's history with AI and record any stable facts found.

    Idempotent: already-known facts are skipped, and single-valued facts
    (role/employer/location) supersede older ones instead of duplicating."""
    contact = _get_contact_or_404(db, contact_id)
    detected = ai.extract_facts(contact)
    saved = []
    for f in detected:
        try:
            fact_type = schemas_fact_type(f.get("fact_type"))
        except ValueError:
            continue
        saved.append(
            insights_service.add_fact(
                db,
                contact,
                fact_type=fact_type,
                value=f.get("value", "").strip(),
                confidence=_confidence_to_float(f.get("confidence")),
                source="ai",
            )
        )
    return saved


@router.patch("/facts/{fact_id}", response_model=ContactFactOut)
def update_fact(
    fact_id: int, payload: ContactFactUpdate, db: Session = Depends(get_db)
):
    fact = _get_fact_or_404(db, fact_id)
    return insights_service.update_fact(db, fact, payload)


@router.post("/facts/{fact_id}/invalidate", response_model=ContactFactOut)
def invalidate_fact(fact_id: int, db: Session = Depends(get_db)):
    fact = _get_fact_or_404(db, fact_id)
    return insights_service.invalidate_fact(db, fact)


def schemas_fact_type(raw):
    from app.modules.insights.models import FactType

    if not raw:
        return FactType.other
    return FactType(str(raw).lower())


def _confidence_to_float(raw) -> float:
    mapping = {"low": 0.4, "medium": 0.7, "high": 0.9}
    if isinstance(raw, (int, float)):
        return max(0.0, min(1.0, float(raw)))
    return mapping.get(str(raw).lower(), 0.7)
