"""Midday check-in (silence-aware) and weekly review text."""

from datetime import datetime, timedelta, timezone


def _due(db, name, days=90):
    from app import warmth
    from app.modules.contacts.models import Contact, Frequency
    from app.modules.interactions.models import Channel, Direction, Interaction

    c = Contact(first_name=name, contact_frequency=Frequency.monthly)
    db.add(c); db.flush()
    db.add(Interaction(contact_id=c.id,
        occurred_at=datetime.now(timezone.utc) - timedelta(days=days),
        channel=Channel.message, direction=Direction.outbound, summary="x", source="telegram"))
    db.flush(); db.refresh(c); warmth.refresh(c); db.commit()
    return c


def test_midday_silent_when_nothing_due(client):
    from app.core.database import SessionLocal
    from app.modules.automation.reviews import midday_checkin_text

    with SessionLocal() as db:
        assert midday_checkin_text(db) is None  # empty network → silence


def test_midday_reports_due(client):
    from app.core.database import SessionLocal
    from app.modules.automation.reviews import midday_checkin_text

    with SessionLocal() as db:
        _due(db, "Overdue Person")
        text = midday_checkin_text(db)
    assert text and "Прострочених" in text and "Overdue Person" in text


def test_weekly_review_counts_reached_and_goals(client):
    from app.core.database import SessionLocal
    from app.modules.automation.reviews import weekly_review_text
    from app.modules.goals.service import create_goal, link_contact
    from app.modules.goals.schemas import GoalIn

    with SessionLocal() as db:
        c = _due(db, "Ally")  # 1 outbound telegram msg this "period"? 90d ago → not in 7d
        goal = create_goal(db, GoalIn(title="Grow"))
        link_contact(db, goal, c)
        text = weekly_review_text(db)
    assert "Тижневий огляд" in text and "Grow" in text
