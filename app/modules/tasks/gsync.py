"""Синхронізація задач із Google Tasks — щоб вони були видні в Календарі.

Правило конфліктів, головне рішення цього модуля:

    наш сервіс — джерело правди для назви, дати й нотаток;
    Google — джерело правди для ВИКОНАННЯ.

Причина проста: назви й дати правляться у нас, а галочку зручно ставити з
телефона. Двобічний «хто останній, той і правий» тут мовчки затирав би
правки, і зрозуміти це можна було б лише постфактум.

Задачі без дати теж потрапляють у список — вони будуть видні в застосунку
Google Tasks, але НЕ в календарі: календар показує тільки те, що має дату.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings

from .models import Task, TaskStatus

logger = logging.getLogger("networking.gsync")


def _due(task: Task) -> str | None:
    """Дата у форматі Google. Час не передаємо — Google його все одно ігнорує."""
    if task.due_date is None:
        return None
    return f"{task.due_date.isoformat()}T00:00:00.000Z"


def _notes(task: Task) -> str | None:
    bits = []
    if task.project:
        bits.append(f"Проєкт: {task.project}")
    if task.counterpart:
        bits.append(f"Хто: {task.counterpart}")
    if task.notes:
        bits.append(task.notes)
    return "\n".join(bits) if bits else None


def syncable(db: Session) -> list[Task]:
    """Задачі, які маємо дзеркалити: живі й не відвʼязані від Google."""
    return list(
        db.scalars(
            select(Task).where(
                Task.deleted_at.is_(None),
                Task.google_sync.is_(True),
            )
        )
    )


def sync(db: Session) -> dict:
    """Один повний прохід. Ніколи не кидає — фон не має падати через Google."""
    from datetime import datetime, timezone

    from app.modules.integrations.google import client as google

    tasklist_id = google.ensure_tasklist(db)
    if not tasklist_id:
        return {"skipped": "google not connected"}

    remote = {item["id"]: item for item in google.list_google_tasks(db, tasklist_id)}
    pushed = completed_from_google = unlinked = 0

    for task in syncable(db):
        try:
            # ── Google -> ми ────────────────────────────────────────────────
            if task.google_task_id:
                item = remote.get(task.google_task_id)
                if item is None:
                    # Видалили в Google. Нашу задачу не чіпаємо — лише
                    # перестаємо її туди пхати, інакше вона воскресала б
                    # щогодини попри волю власника.
                    task.google_task_id = None
                    task.google_sync = False
                    unlinked += 1
                    continue
                if item.get("status") == "completed" and task.status != TaskStatus.done:
                    task.status = TaskStatus.done
                    completed_from_google += 1

            # ── Ми -> Google ────────────────────────────────────────────────
            saved_id = google.upsert_google_task(
                db,
                tasklist_id,
                task_id=task.google_task_id,
                title=task.title,
                notes=_notes(task),
                due=_due(task),
                completed=task.status == TaskStatus.done,
            )
            if saved_id:
                task.google_task_id = saved_id
                task.google_synced_at = datetime.now(timezone.utc)
                pushed += 1
        except Exception as exc:  # pragma: no cover - одна задача не спиняє решту
            logger.warning("gsync task %s failed: %s", task.uid, exc)

    db.commit()
    return {
        "pushed": pushed,
        "completed_from_google": completed_from_google,
        "unlinked": unlinked,
        "tasklist": settings.google_tasklist_title,
    }


def run_sync() -> dict:
    """Точка входу для планувальника."""
    from app.core.database import SessionLocal

    with SessionLocal() as db:
        try:
            return sync(db)
        except Exception as exc:  # pragma: no cover
            logger.warning("gsync failed: %s", exc)
            return {"error": str(exc)}
