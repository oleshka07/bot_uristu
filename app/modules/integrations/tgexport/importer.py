"""Import a Telegram Desktop export (result.json) — the owner's real chats.

Streams the file with ijson (a 275 MB export never sits in memory whole).
Two products per personal chat:

1. **Style**: the owner's own recent messages to each contact become
   few-shot examples (``contact.style_examples``) for draft generation,
   and a global sample feeds one Claude call that writes the owner's
   style card (``StyleProfile``) injected into every draft prompt.
2. **History backfill** (optional): messages become interactions where the
   contact has little/no history, deduped by external id ``tgx:*`` and by
   near-duplicate timestamps against Chater-imported rows.

Contact matching: by telegram_chat_id (export personal_chat id == user id),
then by username/name; unmatched chats are skipped (we only enrich people
already in the CRM — the export contains everyone you ever texted).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models, warmth

logger = logging.getLogger("networking.tgexport")

STYLE_EXAMPLES_PER_CONTACT = 10
GLOBAL_SAMPLE_TARGET = 300
BACKFILL_CAP_PER_CONTACT = 500


@dataclass
class ExportReport:
    chats_seen: int = 0
    chats_matched: int = 0
    style_contacts: int = 0
    interactions_added: int = 0
    my_messages_sampled: int = 0
    style_profile_updated: bool = False
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return self.__dict__


def _msg_text(m: dict) -> str | None:
    """Plain text of an export message (text can be a list of entities)."""
    t = m.get("text")
    if isinstance(t, str):
        return t.strip() or None
    if isinstance(t, list):
        parts = [
            p if isinstance(p, str) else p.get("text", "")
            for p in t
        ]
        return "".join(parts).strip() or None
    return None


def _msg_dt(m: dict) -> datetime | None:
    raw = m.get("date")
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _iter_chats(path: str):
    """Stream chats.list items without loading the whole file."""
    import ijson

    with open(path, "rb") as fh:
        yield from ijson.items(fh, "chats.list.item")


def _match_contact(db: Session, chat: dict) -> models.Contact | None:
    chat_id = chat.get("id")
    if chat_id is not None:
        contact = db.scalar(
            select(models.Contact).where(models.Contact.telegram_chat_id == chat_id)
        )
        if contact:
            return contact
    name = (chat.get("name") or "").strip()
    if name:
        needle = name.casefold()
        for c in db.scalars(select(models.Contact)).unique():
            if c.full_name.casefold() == needle:
                if chat_id is not None and c.telegram_chat_id is None:
                    c.telegram_chat_id = chat_id  # backfill for the proxy
                return c
    return None


def _existing_near(db: Session, contact_id: int, dt: datetime) -> bool:
    """True when an interaction already exists within ±3 minutes — the same
    message imported earlier from the Chater DB under a different id."""
    lo, hi = dt - timedelta(minutes=3), dt + timedelta(minutes=3)
    return (
        db.scalar(
            select(models.Interaction.id).where(
                models.Interaction.contact_id == contact_id,
                models.Interaction.occurred_at >= lo,
                models.Interaction.occurred_at <= hi,
            )
        )
        is not None
    )


def import_export(
    db: Session, path: str, *, backfill: bool = True
) -> ExportReport:
    from app.modules.interactions import service as interactions_service

    report = ExportReport()
    global_sample: list[str] = []

    try:
        chat_iter = _iter_chats(path)
    except Exception as exc:
        report.errors.append(f"Не зміг відкрити експорт: {exc}")
        return report

    for chat in chat_iter:
        if chat.get("type") != "personal_chat":
            continue
        report.chats_seen += 1
        try:
            contact = _match_contact(db, chat)
            if contact is None:
                continue
            report.chats_matched += 1
            chat_id = chat.get("id")

            my_texts: list[str] = []
            added = 0
            for m in chat.get("messages", []):
                if m.get("type") != "message":
                    continue
                text = _msg_text(m)
                if not text:
                    continue
                dt = _msg_dt(m)
                sender = str(m.get("from_id") or "")
                is_mine = sender != f"user{chat_id}"

                if is_mine and 15 <= len(text) <= 400:
                    my_texts.append(text)

                if backfill and dt is not None and added < BACKFILL_CAP_PER_CONTACT:
                    ext = f"tgx:{chat_id}:{m.get('id')}"
                    if interactions_service.interaction_exists(db, contact.id, ext):
                        continue
                    if _existing_near(db, contact.id, dt):
                        continue
                    interactions_service.add_synced_interaction(
                        db,
                        contact,
                        occurred_at=dt,
                        channel=models.Channel.message,
                        direction=(
                            models.Direction.outbound
                            if is_mine
                            else models.Direction.inbound
                        ),
                        summary=text[:300],
                        source="telegram",
                        external_id=ext,
                    )
                    added += 1

            if my_texts:
                recent = my_texts[-STYLE_EXAMPLES_PER_CONTACT:]
                contact.style_examples = json.dumps(recent, ensure_ascii=False)
                report.style_contacts += 1
                # Spread the global sample across many chats.
                if len(global_sample) < GLOBAL_SAMPLE_TARGET:
                    global_sample.extend(recent[-3:])

            if added:
                report.interactions_added += added
                db.flush()
                db.refresh(contact)
                warmth.refresh(contact)
            db.commit()
        except Exception as exc:  # pragma: no cover
            db.rollback()
            report.errors.append(f"{chat.get('name')}: {exc}")

    report.my_messages_sampled = len(global_sample)
    if global_sample:
        report.style_profile_updated = _update_style_profile(db, global_sample)
    return report


def _update_style_profile(db: Session, sample: list[str]) -> bool:
    """One Claude call: distill the owner's writing style into a card."""
    from app.modules.insights import ai

    summary = ai.build_style_card(sample)
    if not summary:
        return False
    profile = db.get(models.StyleProfile, 1)
    if profile is None:
        profile = models.StyleProfile(id=1, summary_md=summary)
        db.add(profile)
    else:
        profile.summary_md = summary
    profile.sample_count = len(sample)
    db.commit()
    return True
