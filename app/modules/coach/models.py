"""Моделі коуча: журнал звірок і налаштування розкладу.

Журнал (``Checkin``) — це і памʼять бота (яке питання висить без відповіді),
і історія прогресу для сторінки та тижневого підсумку. Окремого сховища
«що питали сьогодні» не тримаємо: відкрита звірка — це рядок без
``answered_at``.

Звірка стосується або цілі, або задачі-нагадування — рівно одного з двох.
Один механізм на обидва випадки навмисно: інакше довелося б розрізняти два
конкуруючі «відкриті питання» і вгадувати, на яке з них відповів власник.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, utcnow


class Checkin(Base):
    __tablename__ = "checkins"

    id: Mapped[int] = mapped_column(primary_key=True)
    goal_id: Mapped[int | None] = mapped_column(
        ForeignKey("goals.id", ondelete="CASCADE"), nullable=True, index=True
    )
    task_id: Mapped[int | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), nullable=True, index=True
    )
    # "progress" — що по цілі/задачі; "frequency" — уточнюємо періодичність.
    kind: Mapped[str] = mapped_column(String(20), default="progress")

    asked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
    question: Mapped[str | None] = mapped_column(Text, nullable=True)

    answered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Те, що лягло в журнал цілі — 3-15 слів, без дати.
    summary: Mapped[str | None] = mapped_column(String(300), nullable=True)

    status_before: Mapped[str | None] = mapped_column(String(40), nullable=True)
    status_after: Mapped[str | None] = mapped_column(String(40), nullable=True)

    # "bot" — питання коуча в Telegram, "web" — правка руками на сторінці.
    source: Mapped[str] = mapped_column(String(20), default="bot")
    # Скільки разів нагадували — щоб не колоти двічі за вечір.
    nudges: Mapped[int] = mapped_column(Integer, default=0)

    goal: Mapped["Goal | None"] = relationship()  # noqa: F821
    task: Mapped["Task | None"] = relationship()  # noqa: F821


class CoachSettings(Base):
    """Один рядок на всю систему (id=1): тема року і розклад коуча."""

    __tablename__ = "coach_settings"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    theme: Mapped[str | None] = mapped_column(String(300), nullable=True)
    enabled: Mapped[bool] = mapped_column(default=True)

    ask_hour: Mapped[int] = mapped_column(Integer, default=16)
    nudge_hour: Mapped[int] = mapped_column(Integer, default=22)
    # Понеділок=0 … субота=5 (як у datetime.weekday()).
    weekly_weekday: Mapped[int] = mapped_column(Integer, default=5)
    weekly_hour: Mapped[int] = mapped_column(Integer, default=9)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
