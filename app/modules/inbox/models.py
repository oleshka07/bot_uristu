"""Тред вхідної пошти — одиниця роботи, а не запис в історії.

Синк контактів (``integrations.google``) пише листи в історію взаємодій, щоб
рахувати теплоту стосунку. Тут інша задача: тримати чергу того, що **чекає
на мою відповідь**, включно з листами від людей, яких у базі ще немає.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, utcnow


class EmailThread(Base):
    __tablename__ = "email_threads"

    id: Mapped[int] = mapped_column(primary_key=True)
    # id треда в Gmail — стабільний ключ, за яким тред оновлюється, а не дублюється.
    thread_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    message_id: Mapped[str | None] = mapped_column(String(80), nullable=True)

    subject: Mapped[str] = mapped_column(String(400))
    from_email: Mapped[str] = mapped_column(String(200), index=True)
    from_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    snippet: Mapped[str | None] = mapped_column(Text, nullable=True)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)

    last_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    messages: Mapped[int] = mapped_column(Integer, default=1)
    contact_id: Mapped[int | None] = mapped_column(
        ForeignKey("contacts.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # Результат класифікації: чи чекає лист відповіді і наскільки терміново.
    needs_reply: Mapped[bool] = mapped_column(default=False, index=True)
    urgency: Mapped[str] = mapped_column(String(10), default="normal")
    topic: Mapped[str | None] = mapped_column(String(300), nullable=True)
    classified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # waiting — чекає на мене; answered — я відповів; ignored — свідомо пропущено.
    status: Mapped[str] = mapped_column(String(20), default="waiting", index=True)

    # Чернетка живе спершу тут, а вже потім (за наявності скоупу) у Gmail.
    draft_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    draft_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    drafted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    contact: Mapped["Contact | None"] = relationship()  # noqa: F821
