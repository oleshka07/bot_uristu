"""Idea lifecycle: capture, grow, list, archive."""

from __future__ import annotations

import re
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Idea, IdeaStatus

_LEAD_RE = re.compile(
    r"^\s*(є\s+ідея|нова\s+ідея|ідея|думка|brainstorm|брейншторм)\s*[:—\-]?\s*",
    re.IGNORECASE,
)


def title_from_body(body: str) -> str:
    """A short title from the first line of the body (leading 'є ідея…' stripped)."""
    first = (body or "").strip().splitlines()[0] if (body or "").strip() else ""
    first = _LEAD_RE.sub("", first).strip()
    if not first:
        return "Ідея"
    return first if len(first) <= 60 else first[:60].rstrip() + "…"


def create_idea(db: Session, body: str, title: str | None = None) -> Idea:
    body = (body or "").strip()
    idea = Idea(title=(title or title_from_body(body))[:300], body=body)
    db.add(idea)
    db.commit()
    db.refresh(idea)
    return idea


def append_to_idea(db: Session, idea: Idea, extra: str) -> Idea:
    stamp = datetime.now(timezone.utc).strftime("%d.%m.%Y %H:%M")
    idea.body = f"{idea.body}\n\n— {stamp} —\n{(extra or '').strip()}"
    db.commit()
    db.refresh(idea)
    return idea


def latest_active(db: Session) -> Idea | None:
    return db.scalar(
        select(Idea)
        .where(Idea.status == IdeaStatus.active)
        .order_by(Idea.updated_at.desc())
    )


def list_ideas(db: Session, include_archived: bool = False) -> list[Idea]:
    q = select(Idea).order_by(Idea.updated_at.desc())
    if not include_archived:
        q = q.where(Idea.status == IdeaStatus.active)
    return list(db.scalars(q))


def get_idea(db: Session, idea_id: int) -> Idea | None:
    return db.get(Idea, idea_id)


def set_status(db: Session, idea: Idea, status: IdeaStatus) -> Idea:
    idea.status = status
    db.commit()
    db.refresh(idea)
    return idea


def delete_idea(db: Session, idea: Idea) -> None:
    db.delete(idea)
    db.commit()
