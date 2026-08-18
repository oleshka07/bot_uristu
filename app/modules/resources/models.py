"""Resource — a link or piece of material captured to deal with later.

The GTD gap this closes: a tab you keep open for weeks because closing it
would lose it. Drop it here with a word about why, and it stops being dead
weight in the browser — it becomes a list you actually review.
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, utcnow


class ResourceKind(str, enum.Enum):
    watch = "watch"          # відео / доповідь
    read = "read"            # стаття, дока, тред
    tool = "tool"            # сервіс/інструмент — спробувати
    reference = "reference"  # тримати під рукою
    other = "other"


class ResourceStatus(str, enum.Enum):
    open = "open"        # у списку, чекає
    done = "done"        # переглянув/прочитав
    dropped = "dropped"  # передумав — більше не показувати


class Resource(Base):
    __tablename__ = "resources"

    id: Mapped[int] = mapped_column(primary_key=True)
    url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    title: Mapped[str] = mapped_column(String(300))
    note: Mapped[str | None] = mapped_column(Text, nullable=True)  # навіщо зберіг
    kind: Mapped[ResourceKind] = mapped_column(
        Enum(ResourceKind), default=ResourceKind.other, index=True
    )
    status: Mapped[ResourceStatus] = mapped_column(
        Enum(ResourceStatus), default=ResourceStatus.open, index=True
    )
    # Куди це належить — щоб список читався по проєктах, а не купою.
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), nullable=True
    )
    idea_id: Mapped[int | None] = mapped_column(
        ForeignKey("ideas.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    done_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
