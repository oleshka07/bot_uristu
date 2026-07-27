"""Tasks service: CRUD, Dividify-style ordering, and sync with the PC agent."""

from __future__ import annotations

import secrets
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Task, TaskStatus
from .schemas import SyncRequest, TaskIn, TaskUpdate

# Вага статусу. Immediate завжди перша; hold — вниз; решта нарівні,
# бо «я вже працюю» не має підвищувати пріоритет (лише індикатор).
_RANK = {
    TaskStatus.immediate: 0,
    TaskStatus.urgent: 2,      # 1 — коли настав дедлайн (див. order_key)
    TaskStatus.current: 3,
    TaskStatus.todo: 3,
    TaskStatus.hold: 5,
    TaskStatus.done: 9,
}
_FAR = 10_000  # «дати немає» — в кінець


def new_uid() -> str:
    return secrets.token_hex(3)  # 6 символів — читабельно в focus.md


def order_key(t: Task, today: date | None = None):
    """Статус → дата → тривалість. Коротші задачі вперед: швидкі перемоги."""
    today = today or datetime.now(timezone.utc).date()
    rank = _RANK.get(t.status, 3)
    days = (t.due_date - today).days if t.due_date else _FAR
    if t.status == TaskStatus.urgent and t.due_date and days <= 0:
        rank = 1  # у день дедлайну підіймається майже на самий верх
    return (rank, days, t.duration_min or _FAR, t.id)


def list_tasks(db: Session, *, include_done: bool = False) -> list[Task]:
    stmt = select(Task).where(Task.deleted_at.is_(None))
    if not include_done:
        stmt = stmt.where(Task.status != TaskStatus.done)
    return sorted(db.scalars(stmt).unique(), key=order_key)


def next_task(db: Session) -> Task | None:
    """Що робити прямо зараз — перша за алгоритмом."""
    tasks = list_tasks(db)
    return tasks[0] if tasks else None


def get_by_uid(db: Session, uid: str) -> Task | None:
    return db.scalar(select(Task).where(Task.uid == uid))


def create_task(db: Session, payload: TaskIn) -> Task:
    task = Task(uid=new_uid(), **payload.model_dump())
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def update_task(db: Session, task: Task, payload: TaskUpdate) -> Task:
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(task, field, value)
    db.commit()
    db.refresh(task)
    return task


def soft_delete(db: Session, task: Task) -> None:
    task.deleted_at = datetime.now(timezone.utc)
    db.commit()


def sync(db: Session, payload: SyncRequest) -> tuple[list[Task], int, int]:
    """Злиття з ПК. Перемагає той, хто редагував пізніше (одинокий користувач).

    ponytail: час правки — спільний на весь focus.md, не по задачах. Для одного
    користувача цього досить; на кілька пристроїв знадобиться час на задачу.
    """
    local_time = payload.updated_at or datetime.now(timezone.utc)
    if local_time.tzinfo is None:
        local_time = local_time.replace(tzinfo=timezone.utc)

    applied = 0
    seen: set[str] = set()

    for incoming in payload.tasks:
        task = get_by_uid(db, incoming.uid) if incoming.uid else None
        if task is None:
            task = Task(uid=incoming.uid or new_uid())
            db.add(task)
            applied += 1
        else:
            server_time = task.updated_at
            if server_time and server_time.tzinfo is None:
                server_time = server_time.replace(tzinfo=timezone.utc)
            if server_time and server_time > local_time:
                seen.add(task.uid)
                continue  # на сервері свіжіше — правку з ПК ігноруємо
            applied += 1
        task.title = incoming.title
        task.status = incoming.status
        task.tags = incoming.tags
        if incoming.project is not None:
            task.project = incoming.project
        if incoming.due_date is not None:
            task.due_date = incoming.due_date
        if incoming.duration_min is not None:
            task.duration_min = incoming.duration_min
        task.deleted_at = None
        seen.add(task.uid)

    deleted = 0
    if payload.authoritative:
        # ПК щойно редагували → чого там немає, те видалено
        for task in db.scalars(select(Task).where(Task.deleted_at.is_(None))):
            if task.uid not in seen:
                task.deleted_at = datetime.now(timezone.utc)
                deleted += 1

    db.commit()
    return list_tasks(db, include_done=True), applied, deleted
