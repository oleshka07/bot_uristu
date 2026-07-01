"""Insights API schemas: life events + AI outreach recommendation."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from .models import FactType, LifeEventStatus


class ContactFactIn(BaseModel):
    fact_type: FactType = FactType.other
    value: str = Field(min_length=1, max_length=2000)
    valid_from: date | None = None
    valid_to: date | None = None
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)
    source: str = "manual"
    source_ref: str | None = None


class ContactFactOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    contact_id: int
    fact_type: FactType
    value: str
    valid_from: date | None
    valid_to: date | None
    invalid_at: datetime | None
    confidence: float
    source: str
    source_ref: str | None
    created_at: datetime
    is_current: bool


class ContactFactUpdate(BaseModel):
    value: str | None = Field(default=None, min_length=1, max_length=2000)
    fact_type: FactType | None = None
    valid_to: date | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


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
