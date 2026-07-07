"""Semantic search: build profile text, embed contacts, cosine-rank a query."""

from __future__ import annotations

import hashlib
import json
import logging
import math

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.contacts.models import Contact
from app.modules.insights import llm

from .models import ContactEmbedding

logger = logging.getLogger("networking.search")


def profile_text(contact: Contact) -> str:
    """Compact, embeddable description of a contact."""
    bits = [contact.full_name]
    if contact.position or contact.company:
        bits.append(" ".join(filter(None, [contact.position, contact.company])))
    if contact.location:
        bits.append(contact.location)
    if contact.tags:
        bits.append(", ".join(t.name for t in contact.tags))
    facts = [f.value for f in getattr(contact, "facts", []) if f.is_current]
    if facts:
        bits.append("; ".join(facts))
    if contact.notes:
        bits.append(contact.notes[:400])
    return " | ".join(b for b in bits if b)


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def embed_pending(db: Session, limit: int = 100) -> int:
    """Embed contacts whose profile text is new or changed. Returns count."""
    if not llm.embeddings_enabled():
        return 0
    model = llm.embeddings_model()
    existing = {
        e.contact_id: e
        for e in db.scalars(select(ContactEmbedding)).all()
    }
    todo: list[tuple[Contact, str, str]] = []
    for c in db.scalars(select(Contact)).unique():
        text = profile_text(c)
        if not text.strip():
            continue
        h = _hash(f"{model}:{text}")
        cur = existing.get(c.id)
        if cur is None or cur.text_hash != h:
            todo.append((c, text, h))
        if len(todo) >= limit:
            break
    if not todo:
        return 0

    vectors = llm.embed([t for _, t, _ in todo])
    if not vectors or len(vectors) != len(todo):
        return 0
    done = 0
    for (c, _text, h), vec in zip(todo, vectors):
        row = existing.get(c.id) or ContactEmbedding(contact_id=c.id)
        row.model = model
        row.dim = len(vec)
        row.text_hash = h
        row.vector = json.dumps(vec)
        db.add(row)
        done += 1
    db.commit()
    return done


def pending_count(db: Session) -> int:
    total = db.scalar(select(Contact.id).limit(1))  # cheap existence
    from sqlalchemy import func

    n_contacts = db.scalar(select(func.count(Contact.id))) or 0
    n_embedded = db.scalar(select(func.count(ContactEmbedding.contact_id))) or 0
    return max(n_contacts - n_embedded, 0)


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def semantic_search(db: Session, query: str, k: int = 12) -> list[tuple[int, float]]:
    """Return [(contact_id, score)] ranked by cosine to the query embedding.
    Empty when embeddings are unavailable or nothing is embedded yet."""
    if not (llm.embeddings_enabled() and query.strip()):
        return []
    model = llm.embeddings_model()
    qv = llm.embed([query], input_type="query")
    if not qv:
        return []
    q = qv[0]
    scored: list[tuple[int, float]] = []
    for e in db.scalars(select(ContactEmbedding).where(ContactEmbedding.model == model)):
        try:
            vec = json.loads(e.vector)
        except (ValueError, TypeError):
            continue
        scored.append((e.contact_id, _cosine(q, vec)))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:k]


def similar_contacts(
    db: Session, contact_id: int, k: int = 5
) -> list[tuple[int, float]]:
    """Return [(contact_id, score)] most similar to the given contact by
    embedding cosine (Mesh 'Similar Profiles'). Empty when the contact isn't
    embedded yet or embeddings are unavailable."""
    if not llm.embeddings_enabled():
        return []
    model = llm.embeddings_model()
    base = db.get(ContactEmbedding, contact_id)
    if base is None or base.model != model:
        return []
    try:
        bv = json.loads(base.vector)
    except (ValueError, TypeError):
        return []
    scored: list[tuple[int, float]] = []
    for e in db.scalars(select(ContactEmbedding).where(ContactEmbedding.model == model)):
        if e.contact_id == contact_id:
            continue
        try:
            vec = json.loads(e.vector)
        except (ValueError, TypeError):
            continue
        scored.append((e.contact_id, _cosine(bv, vec)))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:k]
