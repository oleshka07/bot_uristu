"""Interaction API schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from .models import Channel, Direction


class InteractionIn(BaseModel):
    occurred_at: datetime | None = None
    channel: Channel = Channel.message
    direction: Direction = Direction.outbound
    sentiment: float = Field(default=0.0, ge=-1.0, le=1.0)
    summary: str | None = None


class InteractionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    contact_id: int
    occurred_at: datetime
    channel: Channel
    direction: Direction
    sentiment: float
    summary: str | None
    source: str = "manual"
