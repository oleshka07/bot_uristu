"""Telegram Business proxy — draft lifecycle.

Flow (ported from Chater, now powered by our brain):
  incoming DM → match/create contact → log interaction → Claude draft
  (tone + facts + history) → TelegramDraft(pending) → admin preview.
  Approve → send via business connection (as the user) → log outgoing
  interaction → warmth refresh.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import warmth
from app.core.config import settings
from app.modules.contacts.models import Contact, Relationship, Tag
from app.modules.insights import ai
from app.modules.interactions import service as interactions_service
from app.modules.interactions.models import Channel, Direction

from .models import BusinessConnection, DraftKind, DraftStatus, TelegramDraft

logger = logging.getLogger("networking.tgbot")


# ── Business connections ─────────────────────────────────────────────────────


def upsert_connection(
    db: Session, connection_id: str, user_chat_id: int | None, is_enabled: bool
) -> BusinessConnection:
    conn = db.scalar(
        select(BusinessConnection).where(
            BusinessConnection.connection_id == connection_id
        )
    )
    if conn is None:
        conn = BusinessConnection(connection_id=connection_id)
        db.add(conn)
    conn.user_chat_id = user_chat_id
    conn.is_enabled = is_enabled
    db.commit()
    return conn


# ── Contact matching ─────────────────────────────────────────────────────────


def find_or_create_contact(
    db: Session,
    chat_id: int,
    first_name: str,
    last_name: str | None = None,
    username: str | None = None,
) -> tuple[Contact, bool]:
    """Match an incoming DM to a contact by chat id, then username; create a
    new contact otherwise. Backfills telegram_chat_id so the next match is
    O(1) by id. Returns (contact, is_new)."""
    contact = db.scalar(select(Contact).where(Contact.telegram_chat_id == chat_id))
    if contact:
        return contact, False

    if username:
        contact = db.scalar(
            select(Contact).where(Contact.telegram.ilike(f"%{username}%"))
        )
        if contact:
            contact.telegram_chat_id = chat_id
            db.commit()
            return contact, False

    contact = Contact(
        first_name=first_name or "Unknown",
        last_name=last_name,
        telegram=f"@{username}" if username else None,
        telegram_chat_id=chat_id,
        relationship_type=Relationship.acquaintance,
    )
    tag = db.scalar(select(Tag).where(Tag.name == "telegram"))
    if tag is None:
        tag = Tag(name="telegram")
        db.add(tag)
        db.flush()
    contact.tags = [tag]
    db.add(contact)
    db.commit()
    db.refresh(contact)
    logger.info("New contact from Telegram DM: %s (%s)", contact.full_name, chat_id)
    return contact, True


# ── Draft lifecycle ──────────────────────────────────────────────────────────


def handle_incoming(
    db: Session,
    *,
    chat_id: int,
    text: str,
    message_id: int,
    first_name: str,
    last_name: str | None,
    username: str | None,
    business_connection_id: str | None,
) -> tuple[TelegramDraft, Contact, bool]:
    """Process an incoming business DM end-to-end (steps 1–4 above)."""
    contact, is_new = find_or_create_contact(
        db, chat_id, first_name, last_name, username
    )

    external_id = f"tgb:{chat_id}:{message_id}"
    if not interactions_service.interaction_exists(db, contact.id, external_id):
        interactions_service.add_synced_interaction(
            db,
            contact,
            occurred_at=datetime.now(timezone.utc),
            channel=Channel.message,
            direction=Direction.inbound,
            summary=text[:300],
            source="telegram",
            external_id=external_id,
        )
        db.refresh(contact)
        warmth.refresh(contact)
        db.commit()

    db.refresh(contact)
    draft_text = ai.draft_reply(contact, text) or ""

    draft = TelegramDraft(
        contact_id=contact.id,
        chat_id=chat_id,
        business_connection_id=business_connection_id,
        kind=DraftKind.reply,
        incoming_text=text,
        draft_text=draft_text,
        status=DraftStatus.pending,
    )
    db.add(draft)
    db.commit()
    db.refresh(draft)
    return draft, contact, is_new


def get_draft(db: Session, draft_id: int) -> TelegramDraft | None:
    return db.get(TelegramDraft, draft_id)


def find_pending_by_admin_message(
    db: Session, admin_message_id: int
) -> TelegramDraft | None:
    return db.scalar(
        select(TelegramDraft).where(
            TelegramDraft.admin_message_id == admin_message_id,
            TelegramDraft.status == DraftStatus.pending,
        )
    )


def set_admin_message(db: Session, draft: TelegramDraft, message_id: int) -> None:
    draft.admin_message_id = message_id
    db.commit()


def update_draft_text(db: Session, draft: TelegramDraft, text: str) -> None:
    draft.draft_text = text
    db.commit()


def mark(db: Session, draft: TelegramDraft, status: DraftStatus) -> None:
    draft.status = status
    if status == DraftStatus.sent:
        draft.sent_at = datetime.now(timezone.utc)
    db.commit()


def approve_and_send(db: Session, client, draft: TelegramDraft) -> bool:
    """Send the draft to the contact via the business connection (as the
    user), log the outgoing interaction, refresh warmth."""
    if not draft.draft_text.strip():
        return False
    result = client.send_message(
        draft.chat_id,
        draft.draft_text,
        business_connection_id=draft.business_connection_id,
        parse_mode=None,
    )
    if result is None:
        return False

    contact = db.get(Contact, draft.contact_id) if draft.contact_id else None
    if contact:
        message_id = result.get("message_id", 0) if isinstance(result, dict) else 0
        external_id = f"tgb:{draft.chat_id}:out:{message_id or draft.id}"
        if not interactions_service.interaction_exists(db, contact.id, external_id):
            interactions_service.add_synced_interaction(
                db,
                contact,
                occurred_at=datetime.now(timezone.utc),
                channel=Channel.message,
                direction=Direction.outbound,
                summary=draft.draft_text[:300],
                source="telegram",
                external_id=external_id,
            )
            db.refresh(contact)
            warmth.refresh(contact)
            db.commit()

    mark(db, draft, DraftStatus.sent)
    return True


def reformulate(
    db: Session, draft: TelegramDraft, instruction: str
) -> str | None:
    """Rewrite the draft per the admin's instruction (typed or voice)."""
    contact = db.get(Contact, draft.contact_id) if draft.contact_id else None
    if contact is None:
        return None
    new_text = ai.refine_reply(contact, draft.draft_text, instruction)
    if new_text:
        update_draft_text(db, draft, new_text)
    return new_text


# ── Outreach queue ───────────────────────────────────────────────────────────


def get_enabled_connection(db: Session) -> BusinessConnection | None:
    """The user's Telegram Business connection (needed to send as the user)."""
    return db.scalar(
        select(BusinessConnection)
        .where(BusinessConnection.is_enabled.is_(True))
        .order_by(BusinessConnection.updated_at.desc())
    )


def _drafted_today_ids(db: Session) -> set:
    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return set(
        db.scalars(
            select(TelegramDraft.contact_id).where(
                TelegramDraft.kind == DraftKind.outreach,
                TelegramDraft.created_at >= today_start,
            )
        )
    )


def _reachable(db: Session):
    return list(
        db.scalars(
            select(Contact).where(
                Contact.telegram_chat_id.is_not(None),
                Contact.do_not_contact.is_(False),
            )
        ).unique()
    )


def birthday_reason(contact: Contact) -> str:
    return "сьогодні день народження 🎉 — привітай!"


def followup_reason(contact: Contact, days: int) -> str:
    return (
        f"ти написав {days} дн. тому — відповіді не було; "
        "варте м'якого нагадування"
    )


def _awaiting_reply_days(contact: Contact) -> int | None:
    """Days since our last unanswered Telegram message, or None.

    Only the FIRST unanswered message triggers a follow-up (a trailing run
    of 2+ outbound messages means we already nudged — stop nagging)."""
    msgs = [
        i
        for i in contact.interactions
        if i.channel.value == "message" and i.source == "telegram"
    ]
    if not msgs or msgs[0].direction.value != "outbound":
        return None
    run = 0
    for m in msgs:
        if m.direction.value == "outbound":
            run += 1
        else:
            break
    if run >= 2:
        return None
    last = msgs[0].occurred_at
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    days = (datetime.now(timezone.utc) - last).days
    return days if days >= settings.followup_after_days else None


def outreach_reason(contact: Contact) -> str:
    elapsed = round(warmth.days_since_last_contact(contact))
    target = warmth.target_days(contact.contact_frequency)
    overdue = max(elapsed - target, 0)
    reason = (
        f"{elapsed} днів без контакту при цілі «{contact.contact_frequency.value}»"
        + (f" — прострочено на {overdue} дн." if overdue else "")
    )
    fresh_events = [
        e for e in contact.life_events if e.status.value == "new"
    ]
    if fresh_events:
        reason += f" Свіжий привід: {fresh_events[0].title}."
    return reason


def next_outreach_contact(db: Session) -> tuple[Contact, str] | None:
    """The next queue card: (contact, reason).

    Priority: birthdays today → unanswered follow-ups → most overdue.
    A contact is offered at most once per day (outreach drafts are the
    ledger), whatever the user decided about them."""
    drafted_today = _drafted_today_ids(db)
    pool = [c for c in _reachable(db) if c.id not in drafted_today]

    today = datetime.now(timezone.utc).date()
    for c in pool:
        if (
            c.birth_date
            and c.birth_date.month == today.month
            and c.birth_date.day == today.day
        ):
            return c, birthday_reason(c)

    followups = []
    for c in pool:
        days = _awaiting_reply_days(c)
        if days is not None:
            followups.append((days, c))
    if followups:
        followups.sort(key=lambda x: x[0], reverse=True)
        days, c = followups[0]
        return c, followup_reason(c, days)

    due = [c for c in pool if warmth.is_due(c)]
    if not due:
        return None
    due.sort(key=warmth.overdue_ratio, reverse=True)
    return due[0], outreach_reason(due[0])


def stop_list(db: Session, contact: Contact) -> None:
    """Add to the stop-list: never suggested by the queue/digest again
    (reversible from the web UI — the do_not_contact flag on the contact)."""
    contact.do_not_contact = True
    db.commit()


def create_outreach_draft(
    db: Session,
    contact: Contact,
    connection: BusinessConnection,
    reason: str | None = None,
) -> TelegramDraft:
    reason = reason or outreach_reason(contact)
    draft = TelegramDraft(
        contact_id=contact.id,
        chat_id=contact.telegram_chat_id,
        business_connection_id=connection.connection_id,
        kind=DraftKind.outreach,
        incoming_text=reason,  # the "why now" shown on the card
        draft_text=ai.draft_outreach(contact, reason) or "",
        status=DraftStatus.pending,
    )
    db.add(draft)
    db.commit()
    db.refresh(draft)
    return draft


# ── Voice intake ─────────────────────────────────────────────────────────────


def apply_intake(db: Session, parsed: dict) -> tuple[Contact, bool, int]:
    """Apply a parsed voice note: find-or-create the contact by name, add
    facts (deduped by the facts layer), append the note. Returns
    (contact, created, facts_added)."""
    from app.modules.insights import service as insights_service
    from app.modules.insights.models import FactType

    raw_name = (parsed.get("name") or "").strip()
    first = (parsed.get("first_name") or "").strip() or raw_name.split(" ")[0]
    last = (parsed.get("last_name") or "").strip() or (
        raw_name.split(" ", 1)[1] if " " in raw_name else None
    )

    needle = raw_name.casefold()
    contact = next(
        (
            c
            for c in db.scalars(select(Contact)).unique()
            if needle
            and (
                needle in c.full_name.casefold()
                or c.full_name.casefold() in needle
            )
        ),
        None,
    )
    created = False
    if contact is None:
        contact = Contact(first_name=first or "Unknown", last_name=last)
        tag = db.scalar(select(Tag).where(Tag.name == "voice"))
        if tag is None:
            tag = Tag(name="voice")
            db.add(tag)
            db.flush()
        contact.tags = [tag]
        db.add(contact)
        db.flush()
        created = True

    if parsed.get("company") and not contact.company:
        contact.company = parsed["company"][:200]
    if parsed.get("position") and not contact.position:
        contact.position = parsed["position"][:200]

    note = (parsed.get("note") or "").strip()
    if note:
        stamp = datetime.now(timezone.utc).strftime("%d.%m.%Y")
        contact.notes = (
            f"{contact.notes}\n[{stamp}] {note}" if contact.notes else f"[{stamp}] {note}"
        )
    db.commit()
    db.refresh(contact)

    added = 0
    for f in parsed.get("facts") or []:
        value = (f.get("value") or "").strip()
        if not value:
            continue
        try:
            fact_type = FactType(str(f.get("fact_type", "other")).lower())
        except ValueError:
            fact_type = FactType.other
        insights_service.add_fact(
            db, contact, fact_type=fact_type, value=value, source="voice"
        )
        added += 1
    db.refresh(contact)
    return contact, created, added
