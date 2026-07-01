"""Social snapshot model: raw content captured from a contact's social link."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, utcnow


class SocialSnapshot(Base):
    """Raw data captured from a social profile, kept as JSON-ish text so the
    AI can read it and so we can re-process it later as connectors improve."""

    __tablename__ = "social_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    contact_id: Mapped[int] = mapped_column(
        ForeignKey("contacts.id", ondelete="CASCADE"), index=True
    )
    platform: Mapped[str] = mapped_column(String(40))  # instagram / linkedin / ...
    url: Mapped[str] = mapped_column(String(400))
    title: Mapped[str | None] = mapped_column(String(400), nullable=True)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    contact: Mapped["Contact"] = relationship(back_populates="social_snapshots")  # noqa: F821

    __table_args__ = (UniqueConstraint("contact_id", "url", name="uq_contact_social_url"),)
