"""Idea model — a captured thought you can keep growing.

Deliberately simple: a title (auto-derived) and an unbounded body. You dump
an idea by voice/text, then append to it later ("продовж ідею…"). No limit on
count or length.
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, utcnow


class IdeaStatus(str, enum.Enum):
    active = "active"
    archived = "archived"


class Idea(Base):
    __tablename__ = "ideas"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text)  # unbounded — long dumps welcome
    status: Mapped[IdeaStatus] = mapped_column(
        Enum(IdeaStatus), default=IdeaStatus.active, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
