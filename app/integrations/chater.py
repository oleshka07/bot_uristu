"""Chater importer — reuse the existing Telegram bot's PostgreSQL database.

Chater (the user's existing grammY/TypeScript bot) already stores contacts,
their channels (telegram/email/phone) and a full Telegram message history.
This connector reads that database (read-only) and brings it into Networking
AI: contacts become contacts, and Telegram messages become interactions that
feed the warmth score.

The exact Chater column names aren't hard-coded — we introspect each table and
pick the first matching candidate column. Use `inspect()` (a dry run) to see
what was detected before running `import_data()`. Everything is idempotent:
contacts de-dupe by email/telegram, messages by external_id (`tg:<id>`).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import create_engine, inspect as sa_inspect, select, text
from sqlalchemy.orm import Session

from .. import models, warmth
from ..config import settings

logger = logging.getLogger("networking.chater")

_engine = None

# Candidate column names per concept (first match wins).
_C = {
    "contact_id": ["contact_id", "contactId", "contact"],
    "name": ["display_name", "full_name", "name", "title", "first_name"],
    "last_name": ["last_name", "surname"],
    "company": ["company", "organization", "org", "workplace"],
    "birthday": ["birthday", "birth_date", "dob", "birthdate"],
    "notes": ["notes", "note", "summary", "dossier", "description", "bio"],
    "ch_type": ["type", "channel", "kind", "platform", "channel_type"],
    "ch_value": ["value", "address", "identifier", "username", "handle", "contact_value"],
    "msg_text": ["text", "content", "body", "message", "message_text"],
    "msg_time": ["created_at", "timestamp", "date", "sent_at", "ts", "time"],
    "msg_id": ["id", "message_id", "tg_message_id", "telegram_message_id"],
    "msg_dir": ["direction", "is_outgoing", "is_from_me", "outgoing", "from_me", "sender"],
}


@dataclass
class ImportReport:
    contacts_created: int = 0
    contacts_updated: int = 0
    interactions_added: int = 0
    duplicates_removed: int = 0
    errors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return self.__dict__


def _get_engine():
    global _engine
    if not settings.chater_database_url:
        return None
    if _engine is None:
        _engine = create_engine(settings.chater_database_url, pool_pre_ping=True)
    return _engine


def _columns(inspector, table: str) -> list[str]:
    try:
        return [c["name"] for c in inspector.get_columns(table)]
    except Exception:
        return []


def _pick(columns: list[str], key: str) -> str | None:
    lower = {c.lower(): c for c in columns}
    for cand in _C[key]:
        if cand.lower() in lower:
            return lower[cand.lower()]
    return None


def _find_table(tables: list[str], *candidates: str) -> str | None:
    lower = {t.lower(): t for t in tables}
    for cand in candidates:
        if cand.lower() in lower:
            return lower[cand.lower()]
    # fuzzy: any table containing the candidate word
    for cand in candidates:
        for t in tables:
            if cand.lower() in t.lower():
                return t
    return None


def status() -> dict:
    return {"configured": settings.chater_configured}


def inspect() -> dict:
    """Dry run: report the tables and the columns we would map. No writes."""
    engine = _get_engine()
    if engine is None:
        return {"error": "CHATER_DATABASE_URL is not configured."}
    try:
        insp = sa_inspect(engine)
        tables = insp.get_table_names()
    except Exception as exc:
        return {"error": f"Could not connect to Chater DB: {exc}"}

    contacts_t = _find_table(tables, "contacts", "contact")
    channels_t = _find_table(tables, "contact_channels", "channels")
    messages_t = _find_table(tables, "messages", "message")

    def mapping(table, keys):
        if not table:
            return None
        cols = _columns(insp, table)
        return {"table": table, "columns": cols, "mapped": {k: _pick(cols, k) for k in keys}}

    return {
        "tables": tables,
        "contacts": mapping(contacts_t, ["name", "last_name", "company", "birthday", "notes"]),
        "channels": mapping(channels_t, ["contact_id", "ch_type", "ch_value"]),
        "messages": mapping(messages_t, ["contact_id", "msg_text", "msg_time", "msg_id", "msg_dir"]),
    }


def _to_dt(value) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return datetime.now(timezone.utc)


def _direction(value) -> models.Direction:
    if value is None:
        return models.Direction.inbound
    if isinstance(value, bool):
        return models.Direction.outbound if value else models.Direction.inbound
    s = str(value).strip().lower()
    if s in ("out", "outbound", "outgoing", "me", "true", "1", "sent"):
        return models.Direction.outbound
    return models.Direction.inbound


def import_data(db: Session, message_limit: int = 200) -> ImportReport:
    """Import Chater contacts + Telegram messages. `message_limit` caps how
    many recent messages per contact become interactions."""
    report = ImportReport()
    engine = _get_engine()
    if engine is None:
        report.errors.append("CHATER_DATABASE_URL is not configured.")
        return report

    insp = sa_inspect(engine)
    tables = insp.get_table_names()
    contacts_t = _find_table(tables, "contacts", "contact")
    channels_t = _find_table(tables, "contact_channels", "channels")
    messages_t = _find_table(tables, "messages", "message")
    if not contacts_t:
        report.errors.append("No contacts table found in Chater DB.")
        return report

    c_cols = _columns(insp, contacts_t)
    col_name = _pick(c_cols, "name")
    col_last = _pick(c_cols, "last_name")
    col_company = _pick(c_cols, "company")
    col_bday = _pick(c_cols, "birthday")
    col_notes = _pick(c_cols, "notes")
    pk = "id" if "id" in [c.lower() for c in c_cols] else (c_cols[0] if c_cols else "id")

    # Channels indexed by contact id.
    channels: dict = {}
    if channels_t:
        ch_cols = _columns(insp, channels_t)
        ch_cid, ch_type, ch_val = (
            _pick(ch_cols, "contact_id"),
            _pick(ch_cols, "ch_type"),
            _pick(ch_cols, "ch_value"),
        )
        if ch_cid and ch_val:
            with engine.connect() as conn:
                for row in conn.execute(text(f'SELECT * FROM "{channels_t}"')).mappings():
                    cid = row.get(ch_cid)
                    ctype = (str(row.get(ch_type) or "")).lower() if ch_type else ""
                    cval = row.get(ch_val)
                    if cid is None or not cval:
                        continue
                    channels.setdefault(cid, {}).setdefault(ctype or "other", cval)
        else:
            report.notes.append("contact_channels present but columns not mapped; skipped.")

    with engine.connect() as conn:
        contact_rows = list(conn.execute(text(f'SELECT * FROM "{contacts_t}"')).mappings())

    # Map chater contact id -> our Contact
    for row in contact_rows:
        try:
            cid = row.get(pk)
            name = (row.get(col_name) if col_name else None) or "Unknown"
            chans = channels.get(cid, {})
            telegram = _first(chans, ["telegram", "tg", "telegram_username"])
            email = _first(chans, ["email", "mail"])
            phone = _first(chans, ["phone", "tel", "mobile"])

            contact = _find_or_create_contact(
                db,
                external_ref=f"chater:{cid}",
                name=str(name),
                last_name=str(row.get(col_last)) if col_last and row.get(col_last) else None,
                company=str(row.get(col_company)) if col_company and row.get(col_company) else None,
                birthday=row.get(col_bday) if col_bday else None,
                notes=str(row.get(col_notes)) if col_notes and row.get(col_notes) else None,
                telegram=str(telegram) if telegram else None,
                email=str(email) if email else None,
                phone=str(phone) if phone else None,
                report=report,
            )

            if messages_t:
                added = _import_messages(
                    db, engine, insp, messages_t, cid, contact, message_limit
                )
                report.interactions_added += added
                if added:
                    db.refresh(contact)
                    warmth.refresh(contact)
            db.commit()
        except Exception as exc:  # pragma: no cover
            db.rollback()
            report.errors.append(f"Contact import error: {exc}")

    # Clean up any duplicates from earlier imports (idempotent).
    report.duplicates_removed = dedupe(db)
    return report


def _first(d: dict, keys: list[str]):
    for k in keys:
        for actual, val in d.items():
            if k in actual:
                return val
    return None


def _find_or_create_contact(
    db: Session,
    *,
    external_ref: str,
    name: str,
    last_name: str | None,
    company: str | None,
    birthday,
    notes: str | None,
    telegram: str | None,
    email: str | None,
    phone: str | None,
    report: ImportReport,
) -> models.Contact:
    parts = name.strip().split(" ", 1)
    first = parts[0] or name
    last = last_name or (parts[1] if len(parts) > 1 else None)

    # Match priority: stable external_ref → email → telegram → (adopt an
    # un-referenced chater contact by name). Each tier backfills external_ref
    # so subsequent imports are fully idempotent, even with no email/telegram.
    existing = db.scalar(
        select(models.Contact).where(models.Contact.external_ref == external_ref)
    )
    if existing is None and email:
        existing = db.scalar(select(models.Contact).where(models.Contact.email == email))
    if existing is None and telegram:
        existing = db.scalar(
            select(models.Contact).where(models.Contact.telegram == telegram)
        )
    if existing is None:
        existing = db.scalar(
            select(models.Contact)
            .join(models.Contact.tags)
            .where(
                models.Tag.name == "chater",
                models.Contact.external_ref.is_(None),
                models.Contact.first_name == first,
                models.Contact.last_name.is_(last) if last is None
                else models.Contact.last_name == last,
            )
        )

    bday = None
    if birthday:
        try:
            bday = _to_dt(birthday).date()
        except Exception:
            bday = None

    if existing:
        if not existing.external_ref:
            existing.external_ref = external_ref
        existing.telegram = existing.telegram or telegram
        existing.email = existing.email or email
        existing.phone = existing.phone or phone
        existing.company = existing.company or company
        if notes and not existing.notes:
            existing.notes = notes
        report.contacts_updated += 1
        return existing

    contact = models.Contact(
        external_ref=external_ref,
        first_name=first,
        last_name=last,
        relationship_type=models.Relationship.acquaintance,
        contact_frequency=models.Frequency.monthly,
        company=company,
        birth_date=bday,
        email=email,
        phone=phone,
        telegram=telegram,
        notes=notes,
    )
    contact.tags = _chater_tag(db)
    db.add(contact)
    db.flush()
    report.contacts_created += 1
    return contact


def _identity_groups(db: Session) -> dict[tuple, list]:
    contacts = list(
        db.scalars(
            select(models.Contact)
            .join(models.Contact.tags)
            .where(models.Tag.name == "chater")
        ).unique()
    )
    groups: dict[tuple, list] = {}
    for c in contacts:
        key = (
            (c.telegram or "").lower(),
            (c.email or "").lower(),
            c.first_name.lower(),
            (c.last_name or "").lower(),
        )
        groups.setdefault(key, []).append(c)
    return groups


def duplicate_count(db: Session) -> dict:
    """How many chater contacts are duplicates (for diagnostics)."""
    try:
        groups = _identity_groups(db)
        extra = sum(len(m) - 1 for m in groups.values() if len(m) > 1)
        return {"unique": len(groups), "duplicate_extras": extra}
    except Exception as exc:  # pragma: no cover
        return {"error": str(exc)}


def dedupe(db: Session) -> int:
    """Remove duplicate chater-imported contacts, keeping the richest copy
    (most interactions, then lowest id). Returns how many were removed.

    Grouping key: external_ref when set, else (telegram, email, name). Only
    contacts tagged 'chater' are considered, so manual contacts are untouched.
    """
    # Group by identity (not by external_ref) so that a legacy duplicate with
    # no external_ref and a freshly-stamped copy of the same person collapse
    # together. Same telegram/email ⇒ same person; same name with no
    # telegram/email is indistinguishable to us, so treat as the same too.
    groups = _identity_groups(db)

    removed = 0
    for members in groups.values():
        if len(members) < 2:
            continue
        members.sort(key=lambda c: (len(c.interactions), -c.id), reverse=True)
        keep = members[0]
        if keep.external_ref is None:
            # Prefer a ref-bearing duplicate to keep, if any.
            for m in members:
                if m.external_ref:
                    keep = m
                    break
        for c in members:
            if c.id != keep.id:
                db.delete(c)
                removed += 1
    if removed:
        db.commit()
    return removed


def _chater_tag(db: Session) -> list[models.Tag]:
    tag = db.scalar(select(models.Tag).where(models.Tag.name == "chater"))
    if tag is None:
        tag = models.Tag(name="chater")
        db.add(tag)
        db.flush()
    return [tag]


def _import_messages(
    db: Session, engine, insp, messages_t: str, chater_cid, contact, limit: int
) -> int:
    from .. import crud

    cols = _columns(insp, messages_t)
    m_cid = _pick(cols, "contact_id")
    m_text = _pick(cols, "msg_text")
    m_time = _pick(cols, "msg_time")
    m_id = _pick(cols, "msg_id")
    m_dir = _pick(cols, "msg_dir")
    if not (m_cid and m_id):
        return 0

    order = f'ORDER BY "{m_time}" DESC' if m_time else ""
    sql = text(
        f'SELECT * FROM "{messages_t}" WHERE "{m_cid}" = :cid {order} LIMIT :lim'
    )
    added = 0
    with engine.connect() as conn:
        rows = list(conn.execute(sql, {"cid": chater_cid, "lim": limit}).mappings())
    for row in rows:
        ext = f"tg:{row.get(m_id)}"
        if crud.interaction_exists(db, contact.id, ext):
            continue
        body = (row.get(m_text) if m_text else None) or "(message)"
        occurred = _to_dt(row.get(m_time)) if m_time else datetime.now(timezone.utc)
        direction = _direction(row.get(m_dir)) if m_dir else models.Direction.inbound
        crud.add_synced_interaction(
            db,
            contact,
            occurred_at=occurred,
            channel=models.Channel.message,
            direction=direction,
            summary=str(body)[:300],
            source="telegram",
            external_id=ext,
        )
        added += 1
    return added
