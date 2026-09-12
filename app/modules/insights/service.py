"""Insights domain service: life events + stable contact facts."""

from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.contacts.models import Contact

from .models import ContactFact, FactType, LifeEvent
from .schemas import ContactFactUpdate, LifeEventUpdate

# Fact types that hold a single current value — a new one supersedes the old.
SINGLE_VALUED = {FactType.role, FactType.employer, FactType.location}


def add_life_event(
    db: Session,
    contact: Contact,
    *,
    event_type: str,
    title: str,
    description: str | None = None,
    event_date: date | None = None,
    source: str = "manual",
    suggested_message: str | None = None,
) -> LifeEvent:
    ev = LifeEvent(
        contact_id=contact.id,
        event_type=event_type,
        title=title,
        description=description,
        event_date=event_date,
        source=source,
        suggested_message=suggested_message,
    )
    db.add(ev)
    db.commit()
    db.refresh(ev)
    return ev


def update_life_event(
    db: Session, event: LifeEvent, payload: LifeEventUpdate
) -> LifeEvent:
    if payload.status is not None:
        event.status = payload.status
    if payload.suggested_message is not None:
        event.suggested_message = payload.suggested_message
    db.commit()
    db.refresh(event)
    return event


def get_life_event(db: Session, event_id: int) -> LifeEvent | None:
    return db.get(LifeEvent, event_id)


# ── Contact facts ────────────────────────────────────────────────────────────


def current_facts(db: Session, contact_id: int) -> list[ContactFact]:
    """All facts that are still current (not superseded / not expired)."""
    facts = db.scalars(
        select(ContactFact)
        .where(ContactFact.contact_id == contact_id)
        .order_by(ContactFact.fact_type, ContactFact.created_at.desc())
    )
    return [f for f in facts if f.is_current]


def get_fact(db: Session, fact_id: int) -> ContactFact | None:
    return db.get(ContactFact, fact_id)


def add_fact(
    db: Session,
    contact: Contact,
    *,
    fact_type: FactType,
    value: str,
    valid_from: date | None = None,
    valid_to: date | None = None,
    confidence: float = 0.7,
    source: str = "manual",
    source_ref: str | None = None,
) -> ContactFact:
    """Record a fact with non-destructive supersession.

    * If an identical current fact of the same type already exists, it is
      returned unchanged (idempotent — safe for re-running AI extraction).
    * For single-valued types (role/employer/location) any other current fact
      of that type is invalidated so only the newest one stays current.
    """
    normalized = value.strip()
    existing_current = [
        f
        for f in contact.facts
        if f.fact_type == fact_type and f.is_current
    ]

    for f in existing_current:
        if f.value.strip().casefold() == normalized.casefold():
            return f  # already known — no duplicate

    if fact_type in SINGLE_VALUED:
        now = datetime.now(timezone.utc)
        for f in existing_current:
            f.invalid_at = now

    fact = ContactFact(
        contact_id=contact.id,
        fact_type=fact_type,
        value=normalized,
        valid_from=valid_from,
        valid_to=valid_to,
        confidence=confidence,
        source=source,
        source_ref=source_ref,
    )
    db.add(fact)
    db.commit()
    db.refresh(fact)
    return fact


def update_fact(
    db: Session, fact: ContactFact, payload: ContactFactUpdate
) -> ContactFact:
    if payload.value is not None:
        fact.value = payload.value.strip()
    if payload.fact_type is not None:
        fact.fact_type = payload.fact_type
    if payload.valid_to is not None:
        fact.valid_to = payload.valid_to
    if payload.confidence is not None:
        fact.confidence = payload.confidence
    db.commit()
    db.refresh(fact)
    return fact


def invalidate_fact(db: Session, fact: ContactFact) -> ContactFact:
    """Mark a fact as no longer true (kept for history, not deleted)."""
    if fact.invalid_at is None:
        fact.invalid_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(fact)
    return fact


# ── Консолідація памʼяті: епізоди -> досьє + факти ──────────────────────────
#
# Три рівні памʼяті по контакту: сирі взаємодії (interactions), скочене досьє
# (Contact.ai_dossier) і факти з вікном валідності (contact_facts). Перший
# рівень наповнюється сам, два інші — лише тут. Без цієї джоби досьє й факти
# існували б тільки для контактів, де власник натиснув кнопку руками.


def record_facts(db: Session, contact: Contact, detected: list[dict]) -> list[ContactFact]:
    """Кладе витягнуті моделлю факти через add_fact (дедуп + витіснення)."""
    saved: list[ContactFact] = []
    for f in detected:
        raw_type = str(f.get("fact_type") or "other").lower()
        try:
            fact_type = FactType(raw_type)
        except ValueError:
            fact_type = FactType.other
        value = str(f.get("value") or "").strip()
        if not value:
            continue
        saved.append(
            add_fact(
                db,
                contact,
                fact_type=fact_type,
                value=value,
                confidence=_confidence(f.get("confidence")),
                source="ai",
            )
        )
    return saved


def _confidence(raw) -> float:
    mapping = {"low": 0.4, "medium": 0.7, "high": 0.9}
    if isinstance(raw, (int, float)):
        return max(0.0, min(1.0, float(raw)))
    return mapping.get(str(raw).lower(), 0.7)


def extract_and_record_facts(db: Session, contact: Contact) -> list[ContactFact]:
    """Прогін моделі по історії контакту + запис фактів. Ідемпотентно."""
    from app.modules.insights import ai

    return record_facts(db, contact, ai.extract_facts(contact))


def consolidate_contact(db: Session, contact: Contact) -> dict:
    """Переписує досьє і витягає факти з усієї історії контакту.

    Повертає, що змінилося. Якщо AI недоступний — не чіпає ні досьє, ні
    лічильник: інакше контакт вважався б консолідованим, не будучи таким.
    """
    from app.modules.insights import ai

    if not ai.llm.enabled():
        return {"skipped": "ai unavailable"}

    dossier = ai.generate_dossier(contact)
    facts = extract_and_record_facts(db, contact)

    contact.ai_dossier = dossier
    contact.ai_dossier_updated_at = datetime.now(timezone.utc)
    contact.consolidated_count = len(contact.interactions)
    db.commit()
    db.refresh(contact)
    return {"dossier": bool(dossier), "facts": len(facts)}


def due_for_consolidation(db: Session, *, limit: int | None = None) -> list[Contact]:
    """Контакти, чия памʼять відстала від історії.

    Дві умови, кожної досить: назбиралося N нових взаємодій із минулого
    разу, або досьє старше за stale_days і хоч щось із того часу змінилося.
    Найбільш «відсталі» — першими, щоб ліміт на прохід витрачався з користю.
    """
    from datetime import timedelta

    from app.core.config import settings

    every = max(1, settings.consolidate_every)
    stale_after = timedelta(days=settings.consolidate_stale_days)
    now = datetime.now(timezone.utc)

    due: list[tuple[int, Contact]] = []
    for contact in db.scalars(select(Contact)):
        total = len(contact.interactions)
        fresh = total - (contact.consolidated_count or 0)
        if fresh <= 0:
            continue
        updated = contact.ai_dossier_updated_at
        if updated is not None and updated.tzinfo is None:
            updated = updated.replace(tzinfo=timezone.utc)
        stale = updated is None or now - updated > stale_after
        if fresh >= every or stale:
            due.append((fresh, contact))

    due.sort(key=lambda pair: (-pair[0], pair[1].id))
    contacts = [c for _, c in due]
    return contacts[:limit] if limit else contacts


def run_consolidation() -> dict:
    """Фонова джоба: консолідує контакти пачкою, кожен — у своєму try."""
    import logging

    from app.core.config import settings
    from app.core.database import SessionLocal

    from app.modules.aijobs import brain

    report = {"consolidated": 0, "facts": 0, "failed": 0, "due": 0}
    with SessionLocal() as db:
        contacts = due_for_consolidation(db, limit=settings.consolidate_max_per_run)
        report["due"] = len(due_for_consolidation(db))
        # Хто думає — модель через ключ або Claude Code через MCP — вирішує brain.
        report.update(brain.consolidate(db, contacts))
    return report
