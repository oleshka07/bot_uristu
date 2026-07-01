"""Insights domain model: detected/recorded life events + stable contact facts.

Two complementary layers of "what we know" about a contact:
  * LifeEvent — a discrete moment worth acting on (new job, baby, milestone).
  * ContactFact — a durable fact with a validity window. New facts don't
    overwrite old ones; a superseded fact keeps its history (``invalid_at``
    is stamped) so we can answer "what changed since we last spoke".
"""

from __future__ import annotations

import enum
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Enum, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, utcnow


class LifeEventStatus(str, enum.Enum):
    new = "new"
    acknowledged = "acknowledged"
    acted = "acted"
    dismissed = "dismissed"


class FactType(str, enum.Enum):
    """Category of a stable fact about a contact."""

    role = "role"                  # job title / what they do
    employer = "employer"          # where they work
    location = "location"          # where they live / are based
    interest = "interest"          # hobbies, topics they care about
    family = "family"              # partner, kids, relatives
    relationship = "relationship"  # who introduced them, mutual connections
    preference = "preference"      # communication / meeting preferences
    other = "other"


class LifeEvent(Base):
    """A significant event detected (or recorded) for a contact — a moment
    worth reaching out about (new job, baby, marriage, birthday milestone)."""

    __tablename__ = "life_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    contact_id: Mapped[int] = mapped_column(
        ForeignKey("contacts.id", ondelete="CASCADE"), index=True
    )
    event_type: Mapped[str] = mapped_column(String(80))  # e.g. new_job, birth, marriage
    title: Mapped[str] = mapped_column(String(240))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    event_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    source: Mapped[str] = mapped_column(String(80), default="manual")  # manual / instagram / ai
    status: Mapped[LifeEventStatus] = mapped_column(
        Enum(LifeEventStatus), default=LifeEventStatus.new
    )
    suggested_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    contact: Mapped["Contact"] = relationship(back_populates="life_events")  # noqa: F821


class ContactFact(Base):
    """A durable, queryable fact about a contact with a validity window.

    Facts are never destructively overwritten: when a newer fact supersedes an
    older one of the same type, the old row's ``invalid_at`` is stamped and the
    new row is inserted. A fact is *current* when ``invalid_at`` is NULL and
    ``valid_to`` is either NULL or not yet passed. Every derived fact links back
    to the event/interaction that produced it (``source_ref``) for provenance.
    """

    __tablename__ = "contact_facts"

    id: Mapped[int] = mapped_column(primary_key=True)
    contact_id: Mapped[int] = mapped_column(
        ForeignKey("contacts.id", ondelete="CASCADE"), index=True
    )
    fact_type: Mapped[FactType] = mapped_column(
        Enum(FactType), default=FactType.other, index=True
    )
    value: Mapped[str] = mapped_column(Text)  # the fact itself, in plain language

    # Bi-temporal validity
    valid_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    valid_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    invalid_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )  # set when a newer fact supersedes this one

    confidence: Mapped[float] = mapped_column(Float, default=0.7)
    source: Mapped[str] = mapped_column(String(80), default="manual")  # manual / ai / social / chater
    source_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)  # e.g. "interaction:42"
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    contact: Mapped["Contact"] = relationship(back_populates="facts")  # noqa: F821

    @property
    def is_current(self) -> bool:
        if self.invalid_at is not None:
            return False
        if self.valid_to is not None:
            from datetime import date as _date

            return self.valid_to >= _date.today()
        return True
