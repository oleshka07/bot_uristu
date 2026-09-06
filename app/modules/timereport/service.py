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


# ---------------------------------------------------------- денний зріз з ПК

def save_snapshot(db, day, payload: dict):
    """ПК надіслав зріз дня. Пізніший перезаписує ранішній (20:00 → 22:00)."""
    import json

    from .models import DailySnapshot

    row = db.query(DailySnapshot).filter(DailySnapshot.day == day).one_or_none()
    if row is None:
        row = DailySnapshot(day=day)
        db.add(row)
    row.payload = json.dumps(payload, ensure_ascii=False)
    db.commit()
    return row


def _mins(value: int) -> str:
    h, m = divmod(int(value), 60)
    return f"{h}г {m:02d}хв" if h else f"{m}хв"


def daily_digest(db, day=None) -> str | None:
    """Коротке зведення дня для Telegram: час, цілі, поради.

    Свідомо стисло — довгий звіт увечері не читають.
    """
    import json
    from datetime import date as _date

    from .models import DailySnapshot

    day = day or _date.today()
    row = db.query(DailySnapshot).filter(DailySnapshot.day == day).one_or_none()
    if row is None:
        return None
    d = json.loads(row.payload)

    active = d.get("active_min") or 0
    on, off = d.get("on_task_min") or 0, d.get("off_task_min") or 0
    share = round(on / active * 100) if active else 0

    L = [f"📊 <b>День {d['date']}</b> — за компʼютером {_mins(active)}"]
    L.append(f"🎯 На задачах {_mins(on)} ({share}%) · поза списком {_mins(off)}")

    if d.get("goals"):
        L.append("")
        L.append("<b>Вело до цілей:</b>")
        L += [f"• {g['title'][:45]} — {_mins(g['min'])}" for g in d["goals"][:3]]
    elif d.get("tasks"):
        L.append("")
        L.append("<b>Задачі:</b>")
        L += [f"• {t['title'][:45]} — {_mins(t['min'])}" for t in d["tasks"][:3]]

    if d.get("apps"):
        L.append("")
        L.append("<b>Вікна:</b> " + " · ".join(
            f"{a['name'].replace('.exe', '')} {_mins(a['min'])}" for a in d["apps"][:4]))

    if d.get("offtask_top"):
        L.append("")
        L.append("<b>Поза цілями:</b>")
        L += [f"• {w['title'][:45]} — {_mins(w['min'])}" for w in d["offtask_top"][:3]]

    return "\n".join(L)


def send_daily(db) -> bool:
    """О 22:10: зібрати зведення + поради ШІ і надіслати в Telegram."""
    import html
    from datetime import date as _date, datetime as _dt, timezone as _tz

    from app.modules.automation import telegram
    from app.modules.goals.service import active_goals
    from app.modules.insights import ai

    from .models import DailySnapshot

    today = _date.today()
    body = daily_digest(db, today)
    if not body:
        return False

    goals = [g.title for g in active_goals(db)]
    advice = None
    if hasattr(ai, "analyze_day"):
        advice = ai.analyze_day(body, goals)
    if advice:
        body += "\n\n<b>💡 Висновок</b>\n" + html.escape(advice)

    sent = telegram.send_message(body)
    if sent:
        row = db.query(DailySnapshot).filter(DailySnapshot.day == today).one_or_none()
        if row:
            row.sent_at = _dt.now(_tz.utc)
            db.commit()
    return bool(sent)
