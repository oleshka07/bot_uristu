"""Tasks service: CRUD, Dividify-style ordering, and sync with the PC agent."""

from __future__ import annotations

import html
import secrets
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Task, TaskNudge, TaskStatus
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


def nudge_text(db: Session) -> str | None:
    """Що зараз у роботі і що далі — коротко, для Telegram."""
    active = db.scalar(
        select(Task).where(Task.deleted_at.is_(None), Task.status == TaskStatus.current)
    )
    queue = [t for t in list_tasks(db) if t.status != TaskStatus.current]
    if not active and not queue:
        return None

    lines = []
    if active:
        lines.append(f"🎯 <b>Зараз:</b> {html.escape(active.title)}")
    else:
        lines.append("⚠️ <b>Задачу не взято.</b>")
    if queue:
        lines.append("")
        lines.append("<b>Далі:</b>")
        lines += [f"• {html.escape(t.title)}" for t in queue[:3]]
    return "\n".join(lines)


def send_nudge(db: Session) -> bool:
    """Надсилає нагадування в Telegram, прибравши попереднє.

    У чаті завжди рівно одне актуальне повідомлення — старі не накопичуються.
    """
    from app.modules.automation import telegram

    text = nudge_text(db)
    if not text:
        return False

    row = db.get(TaskNudge, 1)
    if row and row.chat_id and row.message_id:
        telegram.delete_message(row.chat_id, row.message_id)

    sent = telegram.send_and_get_id(text)
    if not sent:
        return False
    chat_id, message_id = sent
    if row is None:
        row = TaskNudge(id=1)
        db.add(row)
    row.chat_id, row.message_id = chat_id, message_id
    db.commit()
    return True


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
    parent_of: dict[str, str] = {}   # uid задачі → uid її батька

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
        parent_of[task.uid] = incoming.parent_uid

    # Другим проходом — бо батько міг бути створений у цьому ж запиті.
    db.flush()
    for uid, parent_uid in parent_of.items():
        task = get_by_uid(db, uid)
        parent = get_by_uid(db, parent_uid) if parent_uid else None
        task.parent_id = parent.id if parent and parent.id != task.id else None

    deleted = 0
    if payload.authoritative:
        # ПК щойно редагували → чого там немає, те видалено
        for task in db.scalars(select(Task).where(Task.deleted_at.is_(None))):
            if task.uid not in seen:
                task.deleted_at = datetime.now(timezone.utc)
                deleted += 1

    db.commit()
    return list_tasks(db, include_done=True), applied, deleted
