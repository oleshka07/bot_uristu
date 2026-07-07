"""Feed commands ported from Mesh's Filter Feed: /upcoming, /birthdays,
/events, /reconnect — thin slices over the dashboard data."""

from datetime import date, datetime, timedelta, timezone

from app.modules.telegram_bot.handlers import dispatch

from test_telegram_bot import FakeClient


def _cmd(text: str, uid: int = 1) -> dict:
    return {"update_id": uid, "message": {"chat": {"id": 42}, "text": text}}


def _seed(db):
    from app import crud, warmth
    from app.modules.contacts.models import Contact, Frequency
    from app.modules.interactions.models import Channel, Direction, Interaction

    # Birthday today.
    bday = Contact(
        first_name="Іменинник",
        birth_date=date.today(),
        contact_frequency=Frequency.monthly,
    )
    db.add(bday)

    # Overdue contact (for /reconnect) with a life event (for /events).
    drift = Contact(
        first_name="Остиглий",
        contact_frequency=Frequency.monthly,
        telegram_chat_id=991,
    )
    db.add(drift)
    db.flush()
    db.add(
        Interaction(
            contact_id=drift.id,
            occurred_at=datetime.now(timezone.utc) - timedelta(days=200),
            channel=Channel.message,
            direction=Direction.outbound,
            summary="давня розмова",
        )
    )
    db.flush()
    db.refresh(drift)
    warmth.refresh(drift)
    crud.add_life_event(
        db,
        drift,
        event_type="update",
        title="Змінив роботу",
        description="Перейшов у новий стартап",
        source="test",
    )
    db.commit()


def test_upcoming_and_birthdays_surface_today_birthday(client, monkeypatch):
    monkeypatch.setattr(
        "app.core.config.settings.telegram_chat_id", "42", raising=False
    )
    from app.core.database import SessionLocal

    with SessionLocal() as db:
        _seed(db)

    fake = FakeClient()
    dispatch(fake, _cmd("/upcoming"))
    assert "Іменинник" in fake.sent[-1]["text"]

    fake = FakeClient()
    dispatch(fake, _cmd("/birthdays"))
    txt = fake.sent[-1]["text"]
    assert "Іменинник" in txt and "🎉" in txt  # birthday is today


def test_events_lists_new_life_events(client, monkeypatch):
    monkeypatch.setattr(
        "app.core.config.settings.telegram_chat_id", "42", raising=False
    )
    from app.core.database import SessionLocal

    with SessionLocal() as db:
        _seed(db)

    fake = FakeClient()
    dispatch(fake, _cmd("/events"))
    txt = fake.sent[-1]["text"]
    assert "Остиглий" in txt and "Змінив роботу" in txt


def test_reconnect_lists_overdue_with_queue_button(client, monkeypatch):
    monkeypatch.setattr(
        "app.core.config.settings.telegram_chat_id", "42", raising=False
    )
    from app.core.database import SessionLocal

    with SessionLocal() as db:
        _seed(db)

    fake = FakeClient()
    dispatch(fake, _cmd("/reconnect"))
    last = fake.sent[-1]
    assert "Остиглий" in last["text"]
    # Bridges to the drafting queue.
    assert "q:start" in str(last.get("reply_markup"))
