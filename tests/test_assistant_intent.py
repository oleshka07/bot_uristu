"""Nexus-style assistant: free text → reminder / note / cadence / importance,
plus reminder surfacing in the queue and auto-close on outreach."""

import datetime as dt

from app.modules.telegram_bot.handlers import dispatch

from test_telegram_bot import FakeClient
from test_outreach_queue import _seed_connection, _seed_due_contact


def _msg(text: str, uid: int = 1) -> dict:
    return {"update_id": uid, "message": {"chat": {"id": 42}, "text": text}}


def _intent(monkeypatch, **payload):
    """Force the AI classifier to return a fixed intent for any input."""
    base = {
        "action": "none",
        "person": "",
        "text": "",
        "due_date": "",
        "frequency": "",
        "importance": 0,
    }
    base.update(payload)
    monkeypatch.setattr(
        "app.modules.insights.ai.parse_assistant_intent",
        lambda text, today: dict(base),
    )


def _add_contact(db, name: str, **kw):
    from app.modules.contacts.models import Contact, Frequency

    c = Contact(first_name=name, contact_frequency=kw.pop("frequency", Frequency.monthly))
    for k, v in kw.items():
        setattr(c, k, v)
    db.add(c)
    db.flush()
    db.commit()
    return c.id


def _admin(monkeypatch):
    monkeypatch.setattr(
        "app.core.config.settings.telegram_chat_id", "42", raising=False
    )


def test_remind_creates_reminder_and_tops_the_queue(client, monkeypatch):
    _admin(monkeypatch)
    from app.core.database import SessionLocal

    with SessionLocal() as db:
        _seed_connection(db)
        cid = _seed_due_contact(db, "Олег", 771, days_ago=10)

    yesterday = (dt.date.today() - dt.timedelta(days=1)).isoformat()
    _intent(
        monkeypatch,
        action="remind",
        person="Олег",
        text="написати про зустріч",
        due_date=yesterday,
    )

    fake = FakeClient()
    dispatch(fake, _msg("нагадай написати Олегу про зустріч"))
    assert "Нагадаю" in fake.sent[-1]["text"]

    with SessionLocal() as db:
        from app.modules.automation.reminders import open_reminders

        rs = open_reminders(db)
        assert len(rs) == 1 and rs[0].contact_id == cid

    # A due reminder is the strongest queue signal → top card.
    fake2 = FakeClient()
    dispatch(fake2, {"update_id": 2, "callback_query": {"id": "cb", "data": "q:start"}})
    assert "нагадування" in fake2.sent[-1]["text"]


def test_note_appends_to_contact(client, monkeypatch):
    _admin(monkeypatch)
    from app.core.database import SessionLocal

    with SessionLocal() as db:
        cid = _add_contact(db, "Марія")

    _intent(monkeypatch, action="note", person="Марія", text="переїхала в Берлін")
    fake = FakeClient()
    dispatch(fake, _msg("запиши до Марії, що вона переїхала в Берлін"))
    assert "Записав" in fake.sent[-1]["text"]

    with SessionLocal() as db:
        from app.modules.contacts.models import Contact

        c = db.get(Contact, cid)
        assert "Берлін" in (c.notes or "")


def test_cadence_changes_frequency(client, monkeypatch):
    _admin(monkeypatch)
    from app.core.database import SessionLocal
    from app.modules.contacts.models import Contact, Frequency

    with SessionLocal() as db:
        cid = _add_contact(db, "Іван", frequency=Frequency.weekly)

    _intent(monkeypatch, action="cadence", person="Іван", frequency="monthly")
    fake = FakeClient()
    dispatch(fake, _msg("спілкуватися з Іваном раз на місяць"))
    assert "Каденція" in fake.sent[-1]["text"]

    with SessionLocal() as db:
        c = db.get(Contact, cid)
        assert c.contact_frequency == Frequency.monthly


def test_importance_sets_field(client, monkeypatch):
    _admin(monkeypatch)
    from app.core.database import SessionLocal
    from app.modules.contacts.models import Contact

    with SessionLocal() as db:
        cid = _add_contact(db, "Петро")

    _intent(monkeypatch, action="importance", person="Петро", importance=3)
    fake = FakeClient()
    dispatch(fake, _msg("Петро дуже важливий"))
    assert "Важливість" in fake.sent[-1]["text"]

    with SessionLocal() as db:
        c = db.get(Contact, cid)
        assert c.importance == 3


def test_unresolved_person_falls_back_to_search(client, monkeypatch):
    _admin(monkeypatch)
    from app.core.database import SessionLocal

    with SessionLocal() as db:
        _add_contact(db, "Оксана")

    # Intent names someone we don't have → assistant declines, search runs.
    _intent(monkeypatch, action="note", person="Невідомий", text="щось")
    fake = FakeClient()
    dispatch(fake, _msg("запиши до Невідомого щось"))
    # No note was written; the search path answered instead.
    assert fake.sent  # some reply happened
    assert "Записав" not in fake.sent[-1]["text"]


def test_reminder_autocloses_for_contact(client, monkeypatch):
    from app.core.database import SessionLocal
    from app.modules.automation import reminders as rem

    with SessionLocal() as db:
        cid = _add_contact(db, "Закритий")
        rem.create_reminder(
            db, db.get(_contact_model(), cid), "написати", dt.datetime.now(dt.timezone.utc)
        )
        closed = rem.complete_for_contact(db, cid)
        assert closed == 1
        assert rem.open_reminders(db) == []


def _contact_model():
    from app.modules.contacts.models import Contact

    return Contact
