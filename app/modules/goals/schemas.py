"""Goals API schemas."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from .models import GoalStatus


class GoalContactRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    full_name: str


class GoalIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = None
    status: GoalStatus = GoalStatus.active
    priority: int = Field(default=2, ge=1, le=3)
    target_date: date | None = None
    project_id: int | None = None


class GoalUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    status: GoalStatus | None = None
    priority: int | None = Field(default=None, ge=1, le=3)
    target_date: date | None = None
    project_id: int | None = None


class GoalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    title: str
    description: str | None
    status: GoalStatus
    priority: int
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
