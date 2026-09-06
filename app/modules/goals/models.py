"""Goals domain models: a goal and its linked contacts."""

from __future__ import annotations

import enum
from datetime import date, datetime

from sqlalchemy import (
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, utcnow
from app.modules.contacts.models import Contact


class GoalStatus(enum.StrEnum):
    """Сім статусів трекера цілей — той самий словник, що й у шаблоні.

    Зберігаємо рядком, а не БД-енумом: додати восьмий статус тоді коштує
    рядок коду, а не ALTER TYPE на проді.
    """

    not_started = "not started"
    in_progress = "in progress"
    almost = "almost"
    done = "done"
    cancelled = "cancelled"
    postponed_next_year = "postponed to next year"
    postponed_far_future = "postponed to far future"


#: Статуси, по яких ще є що робити — саме їх питає коуч.
ACTIVE_STATUSES: tuple[GoalStatus, ...] = (
    GoalStatus.not_started,
    GoalStatus.in_progress,
    GoalStatus.almost,
)

#: Як старі чотири статуси лягли на нові сім при переїзді.
LEGACY_STATUS_MAP = {
    "active": GoalStatus.in_progress,
    "paused": GoalStatus.postponed_next_year,
    "done": GoalStatus.done,
    "dropped": GoalStatus.cancelled,
}


class Horizon(enum.StrEnum):
    """На що впливає ціль: сьогодні, наступний рік чи далекий обрій."""

    present = "present"
    future = "future"
    far_future = "far_future"


class Area(enum.StrEnum):
    """Особисте чи робоче — по цьому зрізу рахуються два з трьох дашбордів."""

    pers = "pers"
    work = "work"


goal_contacts = Table(
    "goal_contacts",
    Base.metadata,
    Column("goal_id", ForeignKey("goals.id", ondelete="CASCADE"), primary_key=True),
    Column("contact_id", ForeignKey("contacts.id", ondelete="CASCADE"), primary_key=True),
)


class Goal(Base):
    __tablename__ = "goals"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(40), default=GoalStatus.not_started, index=True
    )
    # Шкала шаблону: 10 (найнижчий) .. 100 (найвищий), крок 10.
    priority: Mapped[int] = mapped_column(Integer, default=50)
    horizon: Mapped[str | None] = mapped_column(String(20), nullable=True)
    area: Mapped[str | None] = mapped_column(String(10), nullable=True)
    owner: Mapped[str | None] = mapped_column(String(120), nullable=True)
    owner2: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # Журнал коуча: рядки «дд.мм.рр: суть» — те, що в шаблоні було колонкою H.
    coach_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    # backref adds ``.goals`` to Contact without contacts importing goals.
    contacts: Mapped[list[Contact]] = relationship(
        secondary=goal_contacts, backref="goals", lazy="selectin"
    )
