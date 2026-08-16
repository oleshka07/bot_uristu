"""Ideas API schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from .models import IdeaStatus


class IdeaIn(BaseModel):
    body: str
    title: str | None = None


class IdeaAppend(BaseModel):
    text: str


class IdeaUpdate(BaseModel):
    status: IdeaStatus


class IdeaOut(BaseModel):
    id: int
    title: str
    body: str
    status: IdeaStatus
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
