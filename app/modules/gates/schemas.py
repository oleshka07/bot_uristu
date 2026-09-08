"""Схеми API воріт."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class GateIn(BaseModel):
    text: str = Field(min_length=1, max_length=300)
    # Ціль можна вказати підрядком назви — скрипту не треба знати id.
    goal: str | None = Field(default=None, max_length=200)
    goal_id: int | None = None
    project: str | None = Field(default=None, max_length=120)


class GateOut(BaseModel):
    uid: str
    text: str
    created_at: datetime
    age_hours: int
    goal: str | None = None
    project: str | None = None


class GateNudge(BaseModel):
    sent: bool
    text: str | None = None
