"""Time-report request lifecycle: request → claim → deliver."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import TimeReportRequest, TimeReportStatus


def request_report(db: Session, period: str = "week") -> TimeReportRequest:
    """Record a pending request (deduped: reuse a fresh pending one)."""
    existing = db.scalar(
        select(TimeReportRequest)
        .where(TimeReportRequest.status == TimeReportStatus.pending)
        .order_by(TimeReportRequest.requested_at.desc())
    )
    if existing is not None:
        return existing
    req = TimeReportRequest(period=period, status=TimeReportStatus.pending)
    db.add(req)
    db.commit()
    db.refresh(req)
    return req


def claim_pending(db: Session) -> TimeReportRequest | None:
    """The PC agent claims the oldest pending request (marks it claimed).

    Stale claims (PC died mid-run) older than 15 min are re-opened so a
    request is never lost."""
    stale = datetime.now(timezone.utc) - timedelta(minutes=15)
    for r in db.scalars(
        select(TimeReportRequest).where(
            TimeReportRequest.status == TimeReportStatus.claimed
        )
    ):
        rq = r.requested_at
        if rq.tzinfo is None:
            rq = rq.replace(tzinfo=timezone.utc)
        if rq < stale:
            r.status = TimeReportStatus.pending
    db.commit()

    req = db.scalar(
        select(TimeReportRequest)
        .where(TimeReportRequest.status == TimeReportStatus.pending)
        .order_by(TimeReportRequest.requested_at)
    )
    if req is None:
        return None
    req.status = TimeReportStatus.claimed
    db.commit()
    db.refresh(req)
    return req


def mark_delivered(db: Session, request_id: int | None) -> None:
    if not request_id:
        return
    req = db.get(TimeReportRequest, request_id)
    if req is not None:
        req.status = TimeReportStatus.delivered
        req.delivered_at = datetime.now(timezone.utc)
        db.commit()
