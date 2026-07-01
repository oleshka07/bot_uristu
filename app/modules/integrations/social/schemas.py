"""Social snapshot + import API schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.modules.insights.schemas import LifeEventOut


class SocialSnapshotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    contact_id: int
    platform: str
    url: str
    title: str | None
    raw_text: str | None
    fetched_at: datetime


class ImportRequest(BaseModel):
    url: str
    analyze: bool = True


class ImportResult(BaseModel):
    snapshot: SocialSnapshotOut
    detected_events: list[LifeEventOut] = Field(default_factory=list)
