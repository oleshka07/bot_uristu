"""Схеми API пошти."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ThreadOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    thread_id: str
    subject: str
    from_email: str
    from_name: str | None
    snippet: str | None
    topic: str | None
    urgency: str
    needs_reply: bool
    status: str
    last_at: datetime
    messages: int
    age_days: int = 0
    contact_id: int | None = None
    contact_name: str | None = None
    draft_text: str | None = None
    in_gmail: bool = False


class ThreadUpdate(BaseModel):
    status: str = Field(pattern="^(waiting|answered|ignored)$")


class SyncOut(BaseModel):
    fetched: int
    added: int
    reopened: int
    updated: int
    classified: int | None = None
    drafted: int | None = None


class StatsOut(BaseModel):
    waiting: int
    urgent: int
    stale: int
    drafted: int
    in_gmail: int
