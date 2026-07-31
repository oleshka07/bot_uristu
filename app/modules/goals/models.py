"""Goals domain models: a goal and its linked contacts."""

from __future__ import annotations

import enum
from datetime import date, datetime

from sqlalchemy import (
    Column,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, utcnow
from app.modules.contacts.models import Contact


class GoalStatus(str, enum.Enum):
    active = "active"
    paused = "paused"
    done = "done"
    dropped = "dropped"


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
    status: Mapped[GoalStatus] = mapped_column(
        Enum(GoalStatus), default=GoalStatus.active, index=True
    )
    priority: Mapped[int] = mapped_column(Integer, default=2)  # 1 low .. 3 high
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
