"""Goals API schemas."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from .models import Area, GoalStatus, Horizon


class GoalContactRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    full_name: str


class GoalIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = None
    status: GoalStatus = GoalStatus.not_started
    # Шкала шаблону: 10..100 з кроком 10.
    priority: int = Field(default=50, ge=10, le=100)
    horizon: Horizon | None = None
    area: Area | None = None
    owner: str | None = Field(default=None, max_length=120)
    owner2: str | None = Field(default=None, max_length=120)
    coach_notes: str | None = None
    target_date: date | None = None
    project_id: int | None = None


class GoalUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    status: GoalStatus | None = None
    priority: int | None = Field(default=None, ge=10, le=100)
    horizon: Horizon | None = None
    area: Area | None = None
    owner: str | None = Field(default=None, max_length=120)
    owner2: str | None = Field(default=None, max_length=120)
    coach_notes: str | None = None
    target_date: date | None = None
    project_id: int | None = None


class GoalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    title: str
    description: str | None
    status: GoalStatus
    priority: int
    horizon: Horizon | None
    area: Area | None
    owner: str | None
    owner2: str | None
    coach_notes: str | None
    target_date: date | None
    project_id: int | None
    created_at: datetime
    contacts: list[GoalContactRef] = Field(default_factory=list)


class GoalBrief(BaseModel):
    """Compact goal reference for a contact card."""

    model_config = ConfigDict(from_attributes=True)
    id: int
    title: str
    status: GoalStatus
