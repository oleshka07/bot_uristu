"""Tasks API schemas."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from .models import TaskStatus


class TaskIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    status: TaskStatus = TaskStatus.todo
    project: str | None = None
    due_date: date | None = None
    duration_min: int | None = Field(default=None, ge=1)
    tags: str | None = None
    notes: str | None = None
    parent_id: int | None = None
    goal_id: int | None = None


class TaskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    status: TaskStatus | None = None
    project: str | None = None
    due_date: date | None = None
    duration_min: int | None = Field(default=None, ge=1)
    tags: str | None = None
    notes: str | None = None
    parent_id: int | None = None
    goal_id: int | None = None


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    uid: str
    title: str
    status: TaskStatus
    project: str | None
    due_date: date | None
    duration_min: int | None
    tags: str | None
    notes: str | None
    parent_id: int | None
    goal_id: int | None
    updated_at: datetime
    deleted_at: datetime | None


class TaskSyncIn(BaseModel):
    """Одна задача з ПК. uid порожній → задача нова, сервер видасть свій."""

    uid: str | None = None
    title: str
    status: TaskStatus = TaskStatus.todo
    project: str | None = None
    due_date: date | None = None
    duration_min: int | None = None
    tags: str | None = None


class SyncRequest(BaseModel):
    tasks: list[TaskSyncIn] = Field(default_factory=list)
    updated_at: datetime | None = None  # час правки focus.md (для «хто новіший»)
    authoritative: bool = False         # так → відсутні uid вважаємо видаленими


class SyncResponse(BaseModel):
    tasks: list[TaskOut]
    applied: int
    deleted: int
