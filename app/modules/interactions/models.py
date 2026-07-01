"""Interactions domain model: a touch-point with a contact."""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, Float, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, utcnow


class Channel(str, enum.Enum):
    call = "call"
    message = "message"
    email = "email"
    meeting = "meeting"
    social = "social"
    event = "event"
    other = "other"


class Direction(str, enum.Enum):
    outbound = "outbound"
    inbound = "inbound"


class Interaction(Base):
    __tablename__ = "interactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    contact_id: Mapped[int] = mapped_column(
        ForeignKey("contacts.id", ondelete="CASCADE"), index=True
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
    channel: Mapped[Channel] = mapped_column(Enum(Channel), default=Channel.message)
    direction: Mapped[Direction] = mapped_column(
        Enum(Direction), default=Direction.outbound
    )
    # Sentiment in [-1, 1]; feeds warmth scoring.
    sentiment: Mapped[float] = mapped_column(Float, default=0.0)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Provenance / de-duplication for auto-synced interactions.
    source: Mapped[str] = mapped_column(String(40), default="manual")  # manual / gmail / gcal
    external_id: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)

    contact: Mapped["Contact"] = relationship(back_populates="interactions")  # noqa: F821

    __table_args__ = (
        UniqueConstraint("contact_id", "external_id", name="uq_interaction_external"),
    )
