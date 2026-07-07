"""B5 Activity — transparency view of what the bot did + system state."""

from app.modules.telegram_bot.handlers import dispatch

from test_telegram_bot import FakeClient


def _cmd(text: str) -> dict:
    return {"update_id": 1, "message": {"chat": {"id": 42}, "text": text}}


def test_activity_reports_new_contacts_and_state(client, monkeypatch):
    monkeypatch.setattr(
        "app.core.config.settings.telegram_chat_id", "42", raising=False
    )
    from app.core.database import SessionLocal
    from app.modules.contacts.models import Contact, Frequency, Tag

    with SessionLocal() as db:
        tag = Tag(name="voice")
        c = Contact(first_name="Новенький", contact_frequency=Frequency.monthly)
        c.tags = [tag]
        db.add(c)
        db.commit()

    fake = FakeClient()
    dispatch(fake, _cmd("/activity"))
    txt = fake.sent[-1]["text"]
    assert "Активність бота" in txt
    assert "Новенький" in txt and "voice" in txt
    assert "AI-провайдер" in txt and "Telegram" in txt
