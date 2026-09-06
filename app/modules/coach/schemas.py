"""Схеми API коуча."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class BucketOut(BaseModel):
    total: int
    counts: dict[str, int]
    percents: dict[str, int]
    done: int
    done_pct: int
    closed: int
    closed_pct: int


class BoardOut(BaseModel):
    theme: str
    pers: BucketOut
    work: BucketOut
    all: BucketOut
    active: int


class SettingsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    theme: str | None
    enabled: bool
    ask_hour: int
    nudge_hour: int
    weekly_weekday: int
    weekly_hour: int


class SettingsUpdate(BaseModel):
    theme: str | None = Field(default=None, max_length=300)
    enabled: bool | None = None
    ask_hour: int | None = Field(default=None, ge=0, le=23)
    nudge_hour: int | None = Field(default=None, ge=0, le=23)
    weekly_weekday: int | None = Field(default=None, ge=0, le=6)
    weekly_hour: int | None = Field(default=None, ge=0, le=23)


class CheckinOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    goal_id: int
    asked_at: datetime
    question: str | None
    answered_at: datetime | None
    answer: str | None
    summary: str | None
    status_before: str | None
    status_after: str | None
    source: str


class AskResult(BaseModel):
    asked: bool
    question: str | None = None
    goal_id: int | None = None
    reason: str | None = None
