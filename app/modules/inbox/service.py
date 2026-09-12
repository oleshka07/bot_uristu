"""Черга пошти: синк тредів, класифікація, чернетки.

Три кроки, навмисно розділені. Синк дешевий і швидкий, класифікація коштує
виклику моделі, чернетка — найдорожча. Тому класифікуємо лише нове, а
чернетки пишемо тільки для того, що справді чекає на відповідь.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.contacts.models import Contact

from .models import EmailThread

logger = logging.getLogger("networking.inbox")

#: Порядок терміновості у черзі.
_URGENCY_RANK = {"high": 0, "normal": 1, "low": 2}


def _match_contact(db: Session, email: str) -> Contact | None:
    if not email:
        return None
    return db.scalars(
        select(Contact).where(func.lower(Contact.email) == email.lower()).limit(1)
    ).first()


def sync(db: Session, *, days: int = 14, limit: int = 60) -> dict:
    """Тягне вхідні треди з Gmail і зводить їх у чергу.

    Тред, на який я відповів останнім, вважається відпрацьованим. Якщо в уже
    закритий тред прийшов новий лист — він знову стає в чергу, а стара
    чернетка скидається: вона відповідала на попереднє повідомлення.
    """
    from app.modules.integrations.google import client as google

    fetched = google.fetch_inbox_threads(db, days=days, limit=limit)
    added = reopened = updated = 0

    for row in fetched:
        thread = db.scalars(
            select(EmailThread).where(EmailThread.thread_id == row["thread_id"])
        ).first()
        answered = row["last_from_me"]

        if thread is None:
            thread = EmailThread(
                thread_id=row["thread_id"],
                status="answered" if answered else "waiting",
            )
            db.add(thread)
            added += 1
        else:
            moved = row["message_id"] != thread.message_id
            if moved and not answered and thread.status != "waiting":
                thread.status = "waiting"
                thread.draft_text = None
                thread.draft_id = None
                thread.drafted_at = None
                thread.classified_at = None
                reopened += 1
            elif moved:
                updated += 1
            if answered:
                thread.status = "answered"

        thread.message_id = row["message_id"]
        thread.subject = row["subject"][:400]
        thread.from_email = row["from_email"][:200]
        thread.from_name = (row["from_name"] or "")[:200] or None
        thread.snippet = row["snippet"]
        thread.body = row["body"]
        thread.last_at = row["last_at"]
        thread.messages = row["messages"]
        if thread.contact_id is None:
            contact = _match_contact(db, row["from_email"])
            if contact is not None:
                thread.contact_id = contact.id

    db.commit()
    return {"fetched": len(fetched), "added": added, "reopened": reopened, "updated": updated}


def untriaged(db: Session, *, limit: int = 20) -> list[EmailThread]:
    """Треди, яких модель ще не бачила (немає розмітки)."""
    return list(
        db.scalars(
            select(EmailThread)
            .where(
                EmailThread.status == "waiting",
                EmailThread.classified_at.is_(None),
            )
            .order_by(EmailThread.last_at.desc())
            .limit(limit)
        )
    )


def undrafted(db: Session, *, limit: int = 5) -> list[EmailThread]:
    """Чекають на відповідь і ще без чернетки."""
    return list(
        db.scalars(
            select(EmailThread)
            .where(
                EmailThread.status == "waiting",
                EmailThread.needs_reply.is_(True),
                EmailThread.draft_text.is_(None),
            )
            .order_by(EmailThread.last_at.desc())
            .limit(limit)
        )
    )


def apply_triage(
    db: Session, thread: EmailThread, *, needs_reply: bool, urgency: str, topic: str | None
) -> EmailThread:
    """Записує розмітку листа — байдуже, хто її дав: модель через ключ чи Claude через MCP."""
    thread.needs_reply = bool(needs_reply)
    thread.urgency = urgency if urgency in {"low", "normal", "high"} else "normal"
    thread.topic = (topic or "").strip()[:200] or None
    thread.classified_at = datetime.now(timezone.utc)
    db.commit()
    return thread


def classify_pending(db: Session, *, limit: int = 20) -> int:
    """Класифікує треди, яких модель ще не бачила. Повертає скільки обробила."""
    from app.modules.insights import ai

    done = 0
    for thread in untriaged(db, limit=limit):
        verdict = ai.triage_email(
            thread.subject, thread.from_email, thread.body or thread.snippet or ""
        )
        if verdict is None:
            continue  # AI недоступний — лишаємо як є, покажемо без розмітки
        apply_triage(
            db, thread,
            needs_reply=verdict["needs_reply"], urgency=verdict["urgency"], topic=verdict["topic"],
        )
        done += 1
    db.commit()
    return done


def save_draft(db: Session, thread: EmailThread, text: str, *, push: bool = True) -> EmailThread:
    """Зберігає готовий текст чернетки і, якщо дозволяє скоуп, кладе її в Gmail."""
    from app.modules.integrations.google import client as google

    text = (text or "").strip()
    if not text:
        return thread
    thread.draft_text = text
    thread.drafted_at = datetime.now(timezone.utc)
    if push:
        # None означає найчастіше брак скоупу gmail.compose — чернетка все одно
        # лишається в нас, і власник бачить її в боті та на сайті.
        thread.draft_id = google.create_draft(
            db,
            thread_id=thread.thread_id,
            to=thread.from_email,
            subject=thread.subject,
            body=text,
        )
    db.commit()
    db.refresh(thread)
    return thread


def make_draft(db: Session, thread: EmailThread, *, push: bool = True) -> EmailThread:
    """Складає чернетку відповіді моделлю через ключ і зберігає її."""
    from app.modules.insights import ai

    contact = db.get(Contact, thread.contact_id) if thread.contact_id else None
    text = ai.draft_email_reply(
        thread.subject, thread.from_email, thread.body or thread.snippet or "", contact
    )
    if not text:
        return thread
    return save_draft(db, thread, text, push=push)


def draft_pending(db: Session, *, limit: int = 5) -> int:
    """Пише чернетки для листів, які чекають на відповідь і ще без чернетки."""
    rows = undrafted(db, limit=limit)
    for thread in rows:
        try:
            make_draft(db, thread)
        except Exception as exc:  # pragma: no cover - одна невдача не спиняє решту
            logger.warning("draft for thread %s failed: %s", thread.thread_id, exc)
    return len(rows)


def waiting(db: Session, *, only_needs_reply: bool = True, limit: int = 50) -> list[EmailThread]:
    """Черга: спершу термінове, далі те, що чекає найдовше."""
    stmt = select(EmailThread).where(EmailThread.status == "waiting")
    if only_needs_reply:
        stmt = stmt.where(EmailThread.needs_reply.is_(True))
    rows = list(db.scalars(stmt))
    rows.sort(key=lambda t: (_URGENCY_RANK.get(t.urgency, 1), t.last_at))
    return rows[:limit]


def age_days(thread: EmailThread) -> int:
    last = thread.last_at
    if last is None:
        return 0
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    return max(0, (datetime.now(timezone.utc) - last).days)


def set_status(db: Session, thread: EmailThread, status: str) -> EmailThread:
    thread.status = status
    db.commit()
    db.refresh(thread)
    return thread


def get(db: Session, thread_pk: int) -> EmailThread | None:
    return db.get(EmailThread, thread_pk)


def stats(db: Session) -> dict:
    rows = list(db.scalars(select(EmailThread).where(EmailThread.status == "waiting")))
    needs = [t for t in rows if t.needs_reply]
    stale = [t for t in needs if age_days(t) >= 2]
    return {
        "waiting": len(needs),
        "urgent": len([t for t in needs if t.urgency == "high"]),
        "stale": len(stale),
        "drafted": len([t for t in needs if t.draft_text]),
        "in_gmail": len([t for t in needs if t.draft_id]),
    }


def run_sync(days: int = 14) -> dict:
    """Повний прохід для планувальника: синк -> класифікація -> чернетки."""
    from app.core.database import SessionLocal

    from app.modules.aijobs import brain

    with SessionLocal() as db:
        report = sync(db, days=days)
        report.update(brain.triage_inbox(db))
        return report


def send_reply(db: Session, thread: EmailThread) -> bool:
    """Надсилає готову чернетку у той самий тред і закриває його в черзі."""
    from app.modules.integrations.google import client as google

    if not thread.draft_text:
        return False
    subject = thread.subject
    if not subject.lower().startswith("re:"):
        subject = f"Re: {subject}"
    sent = google.send_email(
        db,
        to=thread.from_email,
        subject=subject,
        body_html=thread.draft_text,
        thread_id=thread.thread_id,
        plain=True,
    )
    if sent:
        thread.status = "answered"
        db.commit()
    return sent
