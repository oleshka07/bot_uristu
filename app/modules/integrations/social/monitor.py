"""Монітор соцмереж: періодично заходить до людини і читає, що нового.

Цикл на один контакт:
  1. дістати останні дописи профілю (провайдер);
  2. зберегти лише нові — дедуп за id допису;
  3. віддати нові моделі: сталі факти -> у досьє (contact_facts, з посиланням
     на допис), приводи -> у події життя, звідки їх бере обхід і дайджест;
  4. позначити дописи прочитаними, контакт — перевіреним.

Контакти йдуть по колу від найдавніше перевірених, а не лише «прострочені»:
привід написати найчастіше зʼявляється саме в тих, з ким усе добре.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.modules.contacts.models import Contact

from . import posts as providers
from .models import SocialPost

logger = logging.getLogger("networking.social.monitor")


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def candidates(db: Session, *, limit: int | None = None) -> list[Contact]:
    """Кого перевіряти в цьому проході: з Instagram, не в стоп-листі, найдавніше перевірені."""
    every = timedelta(days=max(0, settings.social_monitor_every_days))
    now = datetime.now(timezone.utc)
    rows = []
    for c in db.scalars(select(Contact)):
        if c.do_not_contact or not providers.instagram_handle(c.instagram_url):
            continue
        checked = _aware(c.social_checked_at)
        if checked is not None and now - checked < every:
            continue
        rows.append(c)
    rows.sort(key=lambda c: (_aware(c.social_checked_at) or datetime.min.replace(tzinfo=timezone.utc), c.id))
    return rows[:limit] if limit else rows


def store_new_posts(db: Session, contact: Contact, fetched: list[providers.PostData]) -> list[SocialPost]:
    """Кладе лише невідомі дописи. Повертає саме їх — це і є «що нового»."""
    known = {
        p.external_id
        for p in db.scalars(
            select(SocialPost).where(
                SocialPost.contact_id == contact.id, SocialPost.platform == "instagram"
            )
        )
    }
    new: list[SocialPost] = []
    for item in fetched:
        if item.external_id in known:
            continue
        post = SocialPost(
            contact_id=contact.id,
            platform="instagram",
            external_id=item.external_id,
            url=item.url,
            media_type=item.media_type,
            caption=item.caption,
            alt_text=item.alt_text,
            posted_at=item.posted_at,
        )
        db.add(post)
        new.append(post)
        known.add(item.external_id)
    db.commit()
    for post in new:
        db.refresh(post)
    return new


def unprocessed_posts(db: Session, contact: Contact) -> list[SocialPost]:
    """Дописи, які ще ніхто не читав — їх забирає Claude через MCP або відкат на API."""
    return list(
        db.scalars(
            select(SocialPost)
            .where(SocialPost.contact_id == contact.id, SocialPost.processed_at.is_(None))
            .order_by(SocialPost.posted_at.desc().nullslast(), SocialPost.id.desc())
        )
    )


def mark_processed(db: Session, posts: list[SocialPost]) -> int:
    now = datetime.now(timezone.utc)
    for p in posts:
        p.processed_at = now
    db.commit()
    return len(posts)


def process_posts(db: Session, contact: Contact, new_posts: list[SocialPost]) -> dict:
    """Нові дописи -> факти + приводи. Хто читає — вирішує brain (API або Claude Code).

    Відкладено (Claude прочитає пізніше) — дописи лишаються непрочитаними,
    повертаємо нулі з позначкою ``deferred``.
    """
    from app.modules.aijobs import brain

    if not new_posts:
        return {"facts": 0, "hooks": 0}
    result = brain.social_digest(db, contact, new_posts)
    if result is None:
        return {"facts": 0, "hooks": 0, "deferred": True}
    return result


def process_posts_via_api(db: Session, contact: Contact, new_posts: list[SocialPost]) -> dict:
    """Нові дописи -> факти з провенансом + приводи для контакту (модель через ключ)."""
    from app.modules.insights import ai
    from app.modules.insights import service as insights
    from app.modules.insights.models import FactType

    if not new_posts:
        return {"facts": 0, "hooks": 0}

    payload = [
        {
            "external_id": p.external_id,
            "posted_at": p.posted_at.date().isoformat() if p.posted_at else None,
            "media_type": p.media_type,
            "caption": p.caption,
            "alt_text": p.alt_text,
        }
        for p in new_posts
    ]
    digest = ai.digest_social_posts(contact, payload)
    by_id = {p.external_id: p for p in new_posts}

    facts = 0
    for f in digest.get("facts", []):
        try:
            fact_type = FactType(str(f.get("fact_type") or "other").lower())
        except ValueError:
            fact_type = FactType.other
        post = by_id.get(str(f.get("post_id") or ""))
        insights.add_fact(
            db,
            contact,
            fact_type=fact_type,
            value=str(f["value"]).strip(),
            confidence={"low": 0.4, "medium": 0.7, "high": 0.9}.get(str(f.get("confidence")).lower(), 0.7),
            source="instagram",
            source_ref=f"post:{post.external_id}" if post else None,
        )
        facts += 1

    known_titles = {e.title.casefold() for e in contact.life_events}
    hooks = 0
    for h in digest.get("hooks", []):
        title = str(h["title"]).strip()[:240]
        if not title or title.casefold() in known_titles:
            continue
        post = by_id.get(str(h.get("post_id") or ""))
        insights.add_life_event(
            db,
            contact,
            event_type=str(h.get("event_type") or "update")[:80],
            title=title,
            description=(str(h.get("description") or "").strip() or None),
            event_date=post.posted_at.date() if post and post.posted_at else None,
            source="instagram",
        )
        known_titles.add(title.casefold())
        hooks += 1

    mark_processed(db, new_posts)
    return {"facts": facts, "hooks": hooks}


def check_contact(db: Session, contact: Contact) -> dict:
    """Повний цикл для однієї людини. Позначає перевіреною навіть без нових дописів."""
    fetched = providers.fetch_posts("instagram", contact.instagram_url)
    new_posts = store_new_posts(db, contact, fetched)
    result = process_posts(db, contact, new_posts)
    contact.social_checked_at = datetime.now(timezone.utc)
    db.commit()
    return {"fetched": len(fetched), "new": len(new_posts), **result}


def run_monitor() -> dict:
    """Точка входу планувальника: пачка контактів, кожен у своєму try."""
    from app.core.database import SessionLocal

    report = {"checked": 0, "new_posts": 0, "facts": 0, "hooks": 0, "failed": 0, "skipped": None}
    if not providers.configured("instagram"):
        report["skipped"] = "provider not configured"
        return report
    with SessionLocal() as db:
        for contact in candidates(db, limit=settings.social_monitor_per_run):
            try:
                r = check_contact(db, contact)
                report["checked"] += 1
                report["new_posts"] += r["new"]
                report["facts"] += r["facts"]
                report["hooks"] += r["hooks"]
            except Exception as exc:  # pragma: no cover - одна людина не спиняє прохід
                db.rollback()
                report["failed"] += 1
                logger.warning("social monitor failed for %s: %s", contact.id, exc)
    return report
