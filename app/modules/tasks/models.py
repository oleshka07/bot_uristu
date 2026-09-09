"""Task model — deliberately few fields, Dividify-style.

Order is computed (status → date → duration), never hand-dragged, so there are
no priority numbers or sort columns to maintain.
"""

from __future__ import annotations

import enum
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, utcnow


class TaskStatus(str, enum.Enum):
    immediate = "immediate"      # робити прямо зараз — завжди перша
    urgent = "urgent"            # не можна пропустити — злітає вгору в день дедлайну
    current = "current"          # я вже над цим працюю
    todo = "todo"
    hold = "hold"                # чекає на когось — вниз списку
    done = "done"


class TaskKind(str, enum.Enum):
    task = "task"                # звичайна задача
    duty = "duty"                # обовʼязок: я комусь винен
    expectation = "expectation"  # очікування: я чекаю від когось


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Стабільний короткий ідентифікатор — ним focus.md на ПК зіставляє рядки.
    uid: Mapped[str] = mapped_column(String(12), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(300))
    status: Mapped[TaskStatus] = mapped_column(
        Enum(TaskStatus), default=TaskStatus.todo, index=True
    )
    kind: Mapped[TaskKind] = mapped_column(
        Enum(TaskKind), default=TaskKind.task, index=True
    )
    # `project` — назва (нею оперує focus.md), `project_id` — реальний звʼязок.
    # Обидва встановлюються в одному місці (з назви), тому розійтися не можуть.
    project: Mapped[str | None] = mapped_column(String(120), nullable=True)
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), nullable=True
    )
    item_type: Mapped[str | None] = mapped_column(String(40), nullable=True)   # файл/дзвінок…
    counterpart: Mapped[str | None] = mapped_column(String(120), nullable=True)  # для/від кого
    recur: Mapped[str | None] = mapped_column(String(20), nullable=True)       # monthly/weekly
    # Періодичність нагадувань: словами лежить у `recur`, у днях — тут.
    # Порожньо означає «періодичність ще не названа» — бот її перепитає.
    recur_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    next_remind_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    duration_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tags: Mapped[str | None] = mapped_column(String(300), nullable=True)  # через кому
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), nullable=True
    )
    goal_id: Mapped[int | None] = mapped_column(
        ForeignKey("goals.id", ondelete="SET NULL"), nullable=True
    )
    # Дзеркало в Google Tasks: id рядка там і коли востаннє звіряли.
    google_task_id: Mapped[str | None] = mapped_column(
        String(120), nullable=True, index=True
    )
    google_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Вимикається, коли задачу видалили в Google — щоб ми не пхали її назад.
    google_sync: Mapped[bool] = mapped_column(default=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class TaskNudge(Base):
    """Останнє нагадування в Telegram — рівно один рядок.

    Тримаємо id, щоб нове нагадування прибирало попереднє: у чаті завжди
    одне актуальне повідомлення, а не стрічка застарілих.
    """

    __tablename__ = "task_nudges"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    chat_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
