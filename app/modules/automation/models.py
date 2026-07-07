"""Automation domain models.

``Reminder`` — an explicit, user-set follow-up ("remind me to write Oleg in
3 weeks"). Distinct from the *computed* follow-ups in the outreach queue
(unanswered messages): a Reminder is something the user deliberately asked
for, with its own due date and free-text intent. It surfaces at the top of
the queue when due and closes automatically once the user reaches out.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, utcnow
from app.modules.contacts.models import Contact


class Reminder(Base):
    __tablename__ = "reminders"

    id: Mapped[int] = mapped_column(primary_key=True)
    contact_id: Mapped[int | None] = mapped_column(
        ForeignKey("contacts.id", ondelete="CASCADE"), nullable=True, index=True
    )
    text: Mapped[str] = mapped_column(Text)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    done: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )

    # backref adds ``.reminders`` to Contact without contacts importing this.
    contact: Mapped[Contact | None] = relationship(backref="reminders")
