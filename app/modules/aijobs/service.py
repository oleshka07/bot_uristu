"""Черга: поставити, забрати, закрити, порахувати. Без знання про Claude."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings

from .models import AiJob, AiJobControl


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def enqueue(
    db: Session,
    kind: str,
    payload: dict | None = None,
    *,
    dedupe_key: str | None = None,
    delay_seconds: int = 0,
) -> AiJob:
    """Ставить задачу. Якщо така вже чекає в черзі — повертає її, не дублює."""
    if dedupe_key:
        existing = db.scalar(
            select(AiJob).where(AiJob.dedupe_key == dedupe_key, AiJob.status == "queued")
        )
        if existing is not None:
            return existing
    job = AiJob(
        kind=kind,
        payload=json.dumps(payload or {}, ensure_ascii=False),
        dedupe_key=dedupe_key,
        run_after=_now() + timedelta(seconds=max(0, delay_seconds)),
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def payload_of(job: AiJob) -> dict:
    try:
        return json.loads(job.payload or "{}")
    except ValueError:
        return {}


def claim_next(db: Session) -> AiJob | None:
    """Найстаріша готова задача; позначає її running і рахує спробу."""
    job = db.scalars(
        select(AiJob)
        .where(AiJob.status == "queued", AiJob.run_after <= _now())
        .order_by(AiJob.created_at)
        .limit(1)
    ).first()
    if job is None:
        return None
    job.status = "running"
    job.started_at = _now()
    job.attempts = (job.attempts or 0) + 1
    db.commit()
    db.refresh(job)
    return job


def complete(db: Session, job: AiJob, *, backend: str, result: str | None, usage: dict | None) -> None:
    job.status = "done"
    job.backend = backend
    job.result = (result or "")[:4000] or None
    job.usage = json.dumps(usage or {}, ensure_ascii=False)
    job.finished_at = _now()
    job.error = None
    db.commit()


def fail(db: Session, job: AiJob, error: str, *, retry_in: int = 60) -> bool:
    """Повертає True, якщо задачу поставлено на повтор; False — вичерпано."""
    job.error = (error or "")[:2000]
    if (job.attempts or 0) < settings.aijobs_max_attempts:
        job.status = "queued"
        job.run_after = _now() + timedelta(seconds=retry_in)
        db.commit()
        return True
    job.status = "failed"
    job.finished_at = _now()
    db.commit()
    return False


def requeue_stale(db: Session, *, minutes: int = 15) -> int:
    """running довше N хвилин = воркер помер посеред задачі; повертаємо в чергу."""
    cutoff = _now() - timedelta(minutes=minutes)
    rows = [
        j for j in db.scalars(select(AiJob).where(AiJob.status == "running"))
        if (_aware(j.started_at) or _now()) < cutoff
    ]
    for j in rows:
        j.status = "queued"
        j.run_after = _now()
    db.commit()
    return len(rows)


# ── Керування і статистика ──────────────────────────────────────────────────


def control(db: Session) -> AiJobControl:
    row = db.get(AiJobControl, 1)
    if row is None:
        row = AiJobControl(id=1)
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def is_paused(db: Session) -> bool:
    return bool(control(db).paused)


def set_paused(db: Session, paused: bool) -> None:
    row = control(db)
    row.paused = paused
    db.commit()


def runs_since(db: Session, since: datetime) -> int:
    return db.scalar(
        select(func.count(AiJob.id)).where(AiJob.started_at >= since, AiJob.backend == "claude_code")
    ) or 0


def in_quiet_hours(now: datetime | None = None) -> bool:
    """AIJOBS_QUIET_HOURS="23-7": з 23:00 до 07:00 воркер спить."""
    spec = (settings.aijobs_quiet_hours or "").strip()
    if not spec or "-" not in spec:
        return False
    try:
        start, end = (int(x) for x in spec.split("-", 1))
    except ValueError:
        return False
    hour = (now or datetime.now()).hour
    if start == end:
        return False
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end


def stats(db: Session) -> dict:
    now = _now()
    day = now - timedelta(days=1)
    week = now - timedelta(days=7)
    counts = {
        status: db.scalar(select(func.count(AiJob.id)).where(AiJob.status == status)) or 0
        for status in ("queued", "running", "done", "failed")
    }

    def usage_sum(since: datetime) -> dict:
        cost = tokens_in = tokens_out = runs = 0.0
        for j in db.scalars(select(AiJob).where(AiJob.finished_at >= since, AiJob.backend == "claude_code")):
            runs += 1
            try:
                u = json.loads(j.usage or "{}")
            except ValueError:
                continue
            cost += float(u.get("total_cost_usd") or 0)
            usage = u.get("usage") or {}
            tokens_in += float(usage.get("input_tokens") or 0) + float(usage.get("cache_read_input_tokens") or 0)
            tokens_out += float(usage.get("output_tokens") or 0)
        return {"runs": int(runs), "cost_usd": round(cost, 4), "tokens_in": int(tokens_in), "tokens_out": int(tokens_out)}

    return {
        "mode": settings.background_ai,
        "fallback": settings.background_ai_fallback,
        "paused": is_paused(db),
        "quiet_now": in_quiet_hours(),
        "counts": counts,
        "today": usage_sum(day),
        "week": usage_sum(week),
        "max_per_hour": settings.aijobs_max_per_hour,
    }


def recent(db: Session, limit: int = 30) -> list[AiJob]:
    return list(db.scalars(select(AiJob).order_by(AiJob.created_at.desc()).limit(limit)))
