"""Social import endpoints — capture a snapshot from a link and (optionally)
let the AI detect life events from it."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app import ai, crud, schemas, social
from app.core.database import get_db

router = APIRouter(prefix="/api", tags=["import"])


@router.post(
    "/contacts/{contact_id}/import",
    response_model=schemas.ImportResult,
)
def import_from_url(
    contact_id: int, payload: schemas.ImportRequest, db: Session = Depends(get_db)
):
    contact = crud.get_contact(db, contact_id)
    if contact is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Contact not found")

    data = social.fetch_snapshot(payload.url)
    snapshot = crud.upsert_snapshot(
        db,
        contact,
        platform=data.platform,
        url=data.url,
        title=data.title,
        raw_text=data.raw_text,
    )

    detected: list = []
    if payload.analyze:
        db.refresh(contact)
        for ev in ai.detect_life_events(contact, snapshot):
            life_event = crud.add_life_event(
                db,
                contact,
                event_type=ev.get("event_type", "update"),
                title=ev.get("title", "Detected update"),
                description=ev.get("description"),
                source=data.platform,
            )
            detected.append(life_event)

    return schemas.ImportResult(
        snapshot=schemas.SocialSnapshotOut.model_validate(snapshot),
        detected_events=[schemas.LifeEventOut.model_validate(e) for e in detected],
    )
