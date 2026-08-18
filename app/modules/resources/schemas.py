"""Resources API schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from .models import ResourceKind, ResourceStatus


class ResourceIn(BaseModel):
    url: str | None = None
    note: str | None = None
    title: str | None = None
    kind: ResourceKind | None = None
    project_id: int | None = None
    idea_id: int | None = None


class ResourceUpdate(BaseModel):
    status: ResourceStatus | None = None
    kind: ResourceKind | None = None
    note: str | None = None
    project_id: int | None = None


class ResourceOut(BaseModel):
    id: int
    url: str | None
    title: str
    note: str | None
    kind: ResourceKind
    status: ResourceStatus
    project_id: int | None
    idea_id: int | None
    created_at: datetime

    model_config = {"from_attributes": True}
