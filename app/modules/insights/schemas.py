"""Insights API schemas: life events + AI outreach recommendation."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from .models import LifeEventStatus


class LifeEventIn(BaseModel):
    event_type: str = Field(max_length=80)
    title: str = Field(max_length=240)
    description: str | None = None
    event_date: date | None = None
    source: str = "manual"


class LifeEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    contact_id: int
    event_type: str
    title: str
    description: str | None
    event_date: date | None
    source: str
    status: LifeEventStatus
    suggested_message: str | None
    created_at: datetime


class LifeEventUpdate(BaseModel):
    status: LifeEventStatus | None = None
    suggested_message: str | None = None


class OutreachRecommendation(BaseModel):
    should_contact: bool
    urgency: str
    channel: str
    timing: str
    reason: str
    talking_points: list[str]
    draft_message: str
    source: str = "ai"
