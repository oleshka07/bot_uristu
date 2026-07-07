"""/timeline — one-glance relationship history (Mesh's Timeline)."""

from datetime import datetime, timedelta, timezone

from app.modules.telegram_bot.handlers import dispatch

from test_telegram_bot import FakeClient


def _cmd(text: str) -> dict:
    return {"update_id": 1, "message": {"chat": {"id": 42}, "text": text}}


def test_timeline_shows_history_facts_and_reminders(client, monkeypatch):
    monkeypatch.setattr(
        "app.core.config.settings.telegram_chat_id", "42", raising=False
    )
    from app.core.database import SessionLocal
    from app import warmth
    from app.modules.contacts.models import Contact, Frequency
    from app.modules.interactions.models import Channel, Direction, Interaction
    from app.modules.insights import service as insights_service
    from app.modules.insights.models import FactType
    from app.modules.automation import reminders as rem

    with SessionLocal() as db:
        c = Contact(first_name="Тарас", contact_frequency=Frequency.monthly)
        db.add(c)
        db.flush()
        for days in (300, 5):
            db.add(
                Interaction(
                    contact_id=c.id,
                    occurred_at=datetime.now(timezone.utc) - timedelta(days=days),
                    channel=Channel.message,
                    direction=Direction.outbound,
                    summary=f"розмова {days} днів тому",
                )
            )
        db.flush()
        db.refresh(c)
        warmth.refresh(c)
        insights_service.add_fact(
            db, c, fact_type=FactType.other, value="любить гори", source="test"
        )
        rem.create_reminder(db, c, "подзвонити", datetime.now(timezone.utc))
        db.commit()

    fake = FakeClient()
    dispatch(fake, _cmd("/timeline Тарас"))
    txt = fake.sent[-1]["text"]
    assert "Тарас" in txt
    assert "Історія" in txt and "Всього дотиків: 2" in txt
    assert "любить гори" in txt
    assert "подзвонити" in txt


def test_timeline_unknown_contact(client, monkeypatch):
    monkeypatch.setattr(
        "app.core.config.settings.telegram_chat_id", "42", raising=False
    )
    fake = FakeClient()
    dispatch(fake, _cmd("/timeline Ніхто"))
    assert "Не знайшов" in fake.sent[-1]["text"]
