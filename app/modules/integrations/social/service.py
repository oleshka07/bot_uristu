"""Social integration service: persisting scraped social snapshots."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.contacts.models import Contact

from .models import SocialSnapshot


def upsert_snapshot(
    db: Session,
    contact: Contact,
    *,
    platform: str,
    url: str,
    title: str | None,
    raw_text: str | None,
) -> SocialSnapshot:
    existing = db.scalar(
        select(SocialSnapshot).where(
            SocialSnapshot.contact_id == contact.id,
            SocialSnapshot.url == url,
        )
    )
    if existing:
        existing.platform = platform
        existing.title = title
        existing.raw_text = raw_text
        existing.fetched_at = datetime.now(timezone.utc)
        snapshot = existing
    else:
        snapshot = SocialSnapshot(
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
