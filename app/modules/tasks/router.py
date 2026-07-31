"""Tasks API: CRUD, «що робити зараз», і синхронізація з агентом на ПК."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db

from . import service
from .models import Task, TaskKind
from .schemas import SyncRequest, SyncResponse, TaskIn, TaskOut, TaskUpdate

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


def _task_or_404(db: Session, task_id: int):
    task = db.get(Task, task_id)
    if task is None or task.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Task not found")
    return task


@router.get("", response_model=list[TaskOut])
def list_tasks(
    include_done: bool = Query(default=False),
    kind: TaskKind | None = Query(default=TaskKind.task),
    db: Session = Depends(get_db),
):
    """Впорядковано алгоритмом: статус → дата → тривалість.

    kind=task (за замовчуванням) · duty · expectation · порожньо = всі.
    """
    return service.list_tasks(db, include_done=include_done, kind=kind)


@router.get("/next", response_model=TaskOut | None)
def next_task(db: Session = Depends(get_db)):
    """Одна задача — та, яку робити прямо зараз."""
    return service.next_task(db)


@router.post("", response_model=TaskOut, status_code=status.HTTP_201_CREATED)
def create_task(payload: TaskIn, db: Session = Depends(get_db)):
    return service.create_task(db, payload)


@router.patch("/{task_id}", response_model=TaskOut)
def update_task(task_id: int, payload: TaskUpdate, db: Session = Depends(get_db)):
    return service.update_task(db, _task_or_404(db, task_id), payload)


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_task(task_id: int, db: Session = Depends(get_db)):
    service.soft_delete(db, _task_or_404(db, task_id))


@router.post("/nudge")
def nudge(db: Session = Depends(get_db)):
    """Нагадування в Telegram (кличе агент, коли мене немає за компʼютером)."""
    return {"sent": service.send_nudge(db)}


@router.post("/sync", response_model=SyncResponse)
def sync(payload: SyncRequest, db: Session = Depends(get_db)):
    """Агент з ПК шле свій стан → отримує повний список сервера."""
    tasks, applied, deleted = service.sync(db, payload)
    return SyncResponse(tasks=tasks, applied=applied, deleted=deleted)
