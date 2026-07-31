"""Project — контейнер для цілей, задач, обовʼязків і очікувань."""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, utcnow


class ProjectStatus(str, enum.Enum):
    active = "active"
    paused = "paused"
    done = "done"


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Імʼя унікальне: focus.md на ПК посилається на проєкт саме назвою.
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    status: Mapped[ProjectStatus] = mapped_column(
        Enum(ProjectStatus), default=ProjectStatus.active, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
