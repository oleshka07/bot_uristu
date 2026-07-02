"""Telegram bot domain models: business connections + reply drafts."""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, utcnow


class BusinessConnection(Base):
    """A Telegram Business connection — lets the bot read the user's own DMs
    and send messages on their behalf. Captured lazily from updates."""

    __tablename__ = "business_connections"

    id: Mapped[int] = mapped_column(primary_key=True)
    connection_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    user_chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    is_enabled: Mapped[bool] = mapped_column(default=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class DraftStatus(str, enum.Enum):
    pending = "pending"
    sent = "sent"
    manual = "manual"
    skipped = "skipped"


class DraftKind(str, enum.Enum):
    reply = "reply"        # answer to an incoming DM
    outreach = "outreach"  # proactive message (outreach queue)


class TelegramDraft(Base):
    """A drafted Telegram message awaiting the user's approval.

    The proxy flow: incoming DM → AI draft → preview to the admin with
    buttons → approve sends it via the business connection (as the user).
    ``admin_message_id`` maps the admin's reply/edits back to this draft.
    """

    __tablename__ = "telegram_drafts"

    id: Mapped[int] = mapped_column(primary_key=True)
    contact_id: Mapped[int | None] = mapped_column(
        ForeignKey("contacts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    chat_id: Mapped[int] = mapped_column(BigInteger, index=True)
    business_connection_id: Mapped[str | None] = mapped_column(
        String(120), nullable=True
    )
    kind: Mapped[DraftKind] = mapped_column(Enum(DraftKind), default=DraftKind.reply)
    incoming_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    draft_text: Mapped[str] = mapped_column(Text)
    status: Mapped[DraftStatus] = mapped_column(
        Enum(DraftStatus), default=DraftStatus.pending, index=True
    )
    admin_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    contact: Mapped["Contact"] = relationship()  # noqa: F821
