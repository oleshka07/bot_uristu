"""Insights domain model: detected/recorded life events worth acting on."""

from __future__ import annotations

import enum
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, utcnow


class LifeEventStatus(str, enum.Enum):
    new = "new"
    acknowledged = "acknowledged"
    acted = "acted"
    dismissed = "dismissed"


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
