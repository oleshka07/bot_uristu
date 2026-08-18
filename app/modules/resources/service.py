"""Capture links/material, keep the list reviewable, close items off."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Resource, ResourceKind, ResourceStatus

URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)

# host → kind, for the obvious cases; anything else falls back to the note.
_HOST_KIND = {
    "youtube.com": ResourceKind.watch,
    "youtu.be": ResourceKind.watch,
    "vimeo.com": ResourceKind.watch,
    "loom.com": ResourceKind.watch,
    "medium.com": ResourceKind.read,
    "substack.com": ResourceKind.read,
    "github.com": ResourceKind.tool,
    "docs.google.com": ResourceKind.reference,
    "notion.so": ResourceKind.reference,
}

_WATCH_WORDS = ("подивит", "переглян", "відео", "video", "глянут", "youtube")
_READ_WORDS = ("прочит", "почитат", "стаття", "статтю", "read", "дока", "тред")
_TOOL_WORDS = ("спробува", "інструмент", "сервіс", "tool", "тулз")


def extract_urls(text: str) -> list[str]:
    return URL_RE.findall(text or "")


def guess_kind(url: str | None, note: str | None) -> ResourceKind:
    """Kind from the note first (the user said why), then from the host."""
    n = (note or "").lower()
    if any(w in n for w in _WATCH_WORDS):
        return ResourceKind.watch
    if any(w in n for w in _READ_WORDS):
        return ResourceKind.read
    if any(w in n for w in _TOOL_WORDS):
        return ResourceKind.tool
    if url:
        host = (urlparse(url).hostname or "").lower().removeprefix("www.")
        for known, kind in _HOST_KIND.items():
            if host == known or host.endswith("." + known):
                return kind
    return ResourceKind.other


def title_from(url: str | None, note: str | None) -> str:
    """A readable label without fetching the page (no outbound call needed)."""
    note = (note or "").strip()
    if note:
        first = note.splitlines()[0].strip()
        if len(first) >= 3:
            return first if len(first) <= 120 else first[:120].rstrip() + "…"
    if url:
        p = urlparse(url)
        host = (p.hostname or url).removeprefix("www.")
        slug = (p.path or "").rstrip("/").split("/")[-1].replace("-", " ")
        slug = re.sub(r"\.\w{2,4}$", "", slug).strip()
        return f"{host} — {slug}"[:120] if slug else host[:120]
    return "Матеріал"


def create_resource(
    db: Session,
    *,
    url: str | None,
    note: str | None = None,
    title: str | None = None,
    kind: ResourceKind | None = None,
    project_id: int | None = None,
    idea_id: int | None = None,
) -> Resource:
    r = Resource(
        url=(url or None),
        title=(title or title_from(url, note))[:300],
        note=(note or None),
        kind=kind or guess_kind(url, note),
        project_id=project_id,
        idea_id=idea_id,
    )
    db.add(r)
    db.commit()
    db.refresh(r)
    return r


def find_by_url(db: Session, url: str) -> Resource | None:
    return db.scalar(
        select(Resource).where(
            Resource.url == url, Resource.status == ResourceStatus.open
        )
    )


def list_open(db: Session, kind: ResourceKind | None = None) -> list[Resource]:
    """Oldest first — the ones rotting longest deserve attention first."""
    q = select(Resource).where(Resource.status == ResourceStatus.open)
    if kind is not None:
        q = q.where(Resource.kind == kind)
    return list(db.scalars(q.order_by(Resource.created_at)))


def get_resource(db: Session, resource_id: int) -> Resource | None:
    return db.get(Resource, resource_id)


def set_status(db: Session, r: Resource, status: ResourceStatus) -> Resource:
    r.status = status
    r.done_at = (
        datetime.now(timezone.utc) if status != ResourceStatus.open else None
    )
    db.commit()
    db.refresh(r)
    return r


def open_count(db: Session) -> int:
    return len(list_open(db))


def age_days(r: Resource, now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    created = r.created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return (now - created).days
