"""Dashboard aggregation: daily suggestions, upcoming dates and stats."""

from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import models, schemas, warmth
from app.core.config import settings


def _days_until_anniversary(d: date, today: date) -> int:
    """Days until the next occurrence of month/day (birthday-style recurrence)."""
    try:
        this_year = d.replace(year=today.year)
    except ValueError:  # Feb 29 → treat as Feb 28
        this_year = d.replace(year=today.year, day=28)
    if this_year < today:
        try:
            this_year = d.replace(year=today.year + 1)
        except ValueError:
            this_year = d.replace(year=today.year + 1, day=28)
    return (this_year - today).days


def build_dashboard(db: Session) -> schemas.Dashboard:
    contacts = list(db.scalars(select(models.Contact)).unique())
    today = datetime.now(timezone.utc).date()

    # ── Stats ────────────────────────────────────────────────────────────
    total = len(contacts)
    avg_warmth = (
        round(sum(c.warmth_score for c in contacts) / total, 1) if total else 0.0
    )
    buckets = {"hot": 0, "warm": 0, "cooling": 0, "cold": 0}
    for c in contacts:
        buckets[c.warmth_status] = buckets.get(c.warmth_status, 0) + 1
    due_now = sum(1 for c in contacts if warmth.is_due(c))

    pending_events_q = (
        select(models.LifeEvent)
        .where(models.LifeEvent.status == models.LifeEventStatus.new)
        .order_by(models.LifeEvent.created_at.desc())
    )
    pending_events = list(db.scalars(pending_events_q))

    stats = schemas.DashboardStats(
        total_contacts=total,
        due_now=due_now,
        average_warmth=avg_warmth,
        hot=buckets["hot"],
        warm=buckets["warm"],
        cooling=buckets["cooling"],
        cold=buckets["cold"],
        pending_life_events=len(pending_events),
    )

    # ── Daily suggestions: most overdue, weighted by how cold they are ───
    due = [c for c in contacts if warmth.is_due(c)]
    due.sort(key=lambda c: (warmth.overdue_ratio(c), 100 - c.warmth_score), reverse=True)
    suggestions: list[schemas.SuggestedContact] = []
    for c in due[: settings.daily_suggestions]:
        elapsed = round(warmth.days_since_last_contact(c))
        overdue = max(elapsed - warmth.target_days(c.contact_frequency), 0)
        reason = (
            f"{c.warmth_status.title()} relationship, {overdue} days overdue "
            f"(target: {c.contact_frequency.value})."
        )
        suggestions.append(
            schemas.SuggestedContact(
                contact=schemas.ContactSummary.from_model(c),
                reason=reason,
                days_overdue=overdue,
                days_since_contact=elapsed,
            )
        )

    # ── Upcoming dates: birthdays + key dates within the window ──────────
    window = settings.upcoming_window_days
    upcoming: list[schemas.UpcomingDate] = []
    for c in contacts:
        if c.birth_date:
            days = _days_until_anniversary(c.birth_date, today)
            if 0 <= days <= window:
                upcoming.append(
                    schemas.UpcomingDate(
                        contact=schemas.ContactSummary.from_model(c),
                        label="Birthday",
                        date=c.birth_date,
                        days_away=days,
                    )
                )
        for kd in c.key_dates:
            days = _days_until_anniversary(kd.date, today)
            if 0 <= days <= window:
                upcoming.append(
                    schemas.UpcomingDate(
                        contact=schemas.ContactSummary.from_model(c),
                        label=kd.label,
                        date=kd.date,
                        days_away=days,
                    )
                )
    upcoming.sort(key=lambda u: u.days_away)

    return schemas.Dashboard(
        stats=stats,
        suggestions=suggestions,
        upcoming=upcoming,
        pending_events=[schemas.LifeEventOut.model_validate(e) for e in pending_events[:20]],
        ai_enabled=settings.ai_enabled,
    )
