"""AI endpoints: dossiers, outreach recommendations and event messages."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app import ai, crud, schemas
from app.core.config import settings
from app.core.database import get_db

router = APIRouter(prefix="/api", tags=["ai"])


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
