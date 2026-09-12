"""Задача для фонового AI і один рядок керування (пауза)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, utcnow


class AiJob(Base):
    __tablename__ = "ai_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    # draft_reply, triage_inbox, consolidate, social_digest,
    # coach_question, coach_review, weekly_verdict
    kind: Mapped[str] = mapped_column(String(40), index=True)
    payload: Mapped[str] = mapped_column(Text, default="{}")  # JSON
    # Поки така задача чекає в черзі, друга з тим самим ключем не заводиться.
    dedupe_key: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)

    # queued -> running -> done | failed
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    # Дебаунс: не раніше цього часу (щоб пачка вхідних стала однією задачею).
    run_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Хто виконав: claude_code або api (після відкату).
    backend: Mapped[str | None] = mapped_column(String(20), nullable=True)
    result: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Що повернув claude -p: total_cost_usd, usage, num_turns, duration_ms.
    usage: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON


class AiJobControl(Base):
    """Один рядок (id=1): пауза воркера з панелі."""

    __tablename__ = "ai_jobs_control"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    paused: Mapped[bool] = mapped_column(default=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
