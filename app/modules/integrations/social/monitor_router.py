"""API монітора соцмереж: запустити зараз і подивитись дописи людини."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.modules.contacts.models import Contact

from . import monitor, posts as providers
from .models import SocialPost

router = APIRouter(prefix="/api/social", tags=["social"])


class PostOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    platform: str
    external_id: str
    url: str | None
    media_type: str | None
    caption: str | None
    alt_text: str | None
    posted_at: datetime | None
    processed_at: datetime | None


class MonitorStatus(BaseModel):
    configured: bool
    per_run: int
    every_days: int
    candidates: int


@router.get("/status", response_model=MonitorStatus)
def monitor_status(db: Session = Depends(get_db)):
    from app.core.config import settings

    return MonitorStatus(
        configured=providers.configured("instagram"),
        per_run=settings.social_monitor_per_run,
        every_days=settings.social_monitor_every_days,
        candidates=len(monitor.candidates(db)),
    )


@router.post("/monitor")
def run_now():
    """Той самий прохід, що й за розкладом."""
    return monitor.run_monitor()


@router.post("/contacts/{contact_id}/check")
def check_one(contact_id: int, db: Session = Depends(get_db)):
    contact = db.get(Contact, contact_id)
    if contact is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Contact not found")
    if not providers.instagram_handle(contact.instagram_url):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "У контакту немає посилання на Instagram")
    return monitor.check_contact(db, contact)


@router.get("/contacts/{contact_id}/posts", response_model=list[PostOut])
def contact_posts(contact_id: int, db: Session = Depends(get_db)):
    if db.get(Contact, contact_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Contact not found")
    rows = db.scalars(
        select(SocialPost)
        .where(SocialPost.contact_id == contact_id)
        .order_by(SocialPost.posted_at.desc().nullslast(), SocialPost.id.desc())
        .limit(50)
    )
    return list(rows)
