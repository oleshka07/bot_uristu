"""B3 Similar/Related — semantic neighbours + explicit links (company/goal)."""

from app.modules.telegram_bot.handlers import dispatch

from test_telegram_bot import FakeClient


def _cmd(text: str) -> dict:
    return {"update_id": 1, "message": {"chat": {"id": 42}, "text": text}}


def test_similar_surfaces_same_company_colleague(client, monkeypatch):
    monkeypatch.setattr(
        "app.core.config.settings.telegram_chat_id", "42", raising=False
    )
    from app.core.database import SessionLocal
    from app.modules.contacts.models import Contact, Frequency

    with SessionLocal() as db:
        a = Contact(first_name="Ірина", company="Acme", contact_frequency=Frequency.monthly)
        b = Contact(first_name="Степан", company="Acme", contact_frequency=Frequency.monthly)
        db.add_all([a, b])
        db.commit()

    fake = FakeClient()
    dispatch(fake, _cmd("/similar Ірина"))
    txt = fake.sent[-1]["text"]
    assert "Степан" in txt and "Acme" in txt


def test_similar_unknown_contact(client, monkeypatch):
    monkeypatch.setattr(
        "app.core.config.settings.telegram_chat_id", "42", raising=False
    )
    fake = FakeClient()
    dispatch(fake, _cmd("/similar Привид"))
    assert "Не знайшов" in fake.sent[-1]["text"]
