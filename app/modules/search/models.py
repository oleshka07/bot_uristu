"""Stored contact embeddings for semantic search."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, utcnow


class ContactEmbedding(Base):
    """One embedding vector per contact, of the compact profile text.

    ``text_hash`` lets the embed job skip contacts whose profile hasn't
    changed; ``model`` guards against mixing vectors from different models.
    The vector is stored as a JSON array (no pgvector dependency — cosine is
    computed in Python over a few hundred contacts)."""

    __tablename__ = "contact_embeddings"

    contact_id: Mapped[int] = mapped_column(
        ForeignKey("contacts.id", ondelete="CASCADE"), primary_key=True
    )
    model: Mapped[str] = mapped_column(String(80))
    dim: Mapped[int] = mapped_column(Integer)
    text_hash: Mapped[str] = mapped_column(String(64))
    vector: Mapped[str] = mapped_column(Text)  # JSON array of floats
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
