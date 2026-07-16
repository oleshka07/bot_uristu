"""Per-contact auto-reply pause: log + context, but no auto-draft."""

from app.modules.telegram_bot.handlers import dispatch

from test_telegram_bot import FakeClient, _business_update


def _cmd(text: str) -> dict:
    return {"update_id": 1, "message": {"chat": {"id": 42}, "text": text}}


def _admin(monkeypatch):
    monkeypatch.setattr(
        "app.core.config.settings.telegram_chat_id", "42", raising=False
    )


def test_paused_contact_headsup_not_draft(client, monkeypatch):
    _admin(monkeypatch)
    from app.core.database import SessionLocal
    from app.modules.contacts.models import Contact, Frequency

    with SessionLocal() as db:
        db.add(
            Contact(
                first_name="Олег",
                telegram_chat_id=555001,
                contact_frequency=Frequency.monthly,
                auto_reply_paused=True,
            )
        )
        db.commit()

    fake = FakeClient()
    dispatch(fake, _business_update(text="Зустріч з 15 до 16, ок?"))

    # Heads-up, not a reply draft.
    assert "ти відповідаєш сам" in fake.sent[-1]["text"]

    from sqlalchemy import func, select
    from app.modules.interactions.models import Interaction
    from app.modules.telegram_bot.models import TelegramDraft

    with SessionLocal() as db:
        # The message was still logged (context preserved).
        assert db.scalar(select(func.count(Interaction.id))) >= 1
        # A held, text-less draft exists for on-demand compose.
        held = db.scalar(select(TelegramDraft))
        assert held is not None and held.draft_text == ""


def test_pause_and_resume_commands(client, monkeypatch):
    _admin(monkeypatch)
    from app.core.database import SessionLocal
    from app.modules.contacts.models import Contact, Frequency

    with SessionLocal() as db:
        c = Contact(first_name="Марія", contact_frequency=Frequency.monthly)
        db.add(c)
        db.commit()
        cid = c.id

    fake = FakeClient()
    dispatch(fake, _cmd("/pause Марія"))
    assert "паузі" in fake.sent[-1]["text"]
    with SessionLocal() as db:
        assert db.get(Contact, cid).auto_reply_paused is True

    dispatch(fake, _cmd("/paused"))
    assert "Марія" in fake.sent[-1]["text"]

    dispatch(fake, _cmd("/resume Марія"))
    with SessionLocal() as db:
        assert db.get(Contact, cid).auto_reply_paused is False


def test_range_and_intent_helpers():
    from app.modules.telegram_bot.handlers import (
        _cal_range_from_text, _detect_incoming_intent,
    )

    assert _cal_range_from_text("з 15 до 16") == ((15, 0), (16, 0))
    assert _cal_range_from_text("9:30–11") == ((9, 30), (11, 0))
    assert "meeting" in _detect_incoming_intent("зустріч завтра з 15 до 16")
    assert "task" in _detect_incoming_intent("слухай, можеш підготувати звіт?")
    assert _detect_incoming_intent("ок дякую") == set()


def _paused_contact(db, chat_id, incoming):
    from app.modules.contacts.models import Contact, Frequency
    from app.modules.telegram_bot.models import (
        DraftKind, DraftStatus, TelegramDraft,
    )

    c = Contact(
        first_name="Гість", telegram_chat_id=chat_id,
        contact_frequency=Frequency.monthly, auto_reply_paused=True,
    )
    db.add(c)
    db.flush()
    d = TelegramDraft(
        contact_id=c.id, chat_id=chat_id, kind=DraftKind.reply,
        incoming_text=incoming, draft_text="", status=DraftStatus.pending,
    )
    db.add(d)
    db.commit()
    return d.id, c.id


def test_paused_meeting_button_creates_event(client, monkeypatch):
    _admin(monkeypatch)
    from app.core.database import SessionLocal

    with SessionLocal() as db:
        did, _ = _paused_contact(db, 811, "давай зустріч завтра з 15 до 16, ок?")

    monkeypatch.setattr(
        "app.integrations.google.status", lambda db: {"connected": True}
    )
    captured = {}
    monkeypatch.setattr(
        "app.integrations.google.create_event",
        lambda db, **kw: captured.update(kw) or {"summary": kw["summary"],
                                                 "start": kw["start_local"],
                                                 "html_link": "x", "meet_link": None},
    )
    fake = FakeClient()
    dispatch(
        fake,
        {"update_id": 3, "callback_query": {"id": "cb", "data": f"d:cal:{did}",
         "message": {"chat": {"id": 42}, "message_id": 11}}},
    )
    assert captured["start_local"].endswith("T15:00:00")
    assert captured["end_local"].endswith("T16:00:00")


def test_paused_task_button_creates_reminder(client, monkeypatch):
    _admin(monkeypatch)
    from app.core.database import SessionLocal

    with SessionLocal() as db:
        did, cid = _paused_contact(db, 812, "можеш підготувати звіт до понеділка?")

    fake = FakeClient()
    dispatch(
        fake,
        {"update_id": 4, "callback_query": {"id": "cb", "data": f"d:tk:{did}",
         "message": {"chat": {"id": 42}, "message_id": 12}}},
    )
    from app.modules.automation.reminders import open_reminders

    with SessionLocal() as db:
        rs = open_reminders(db)
        assert rs and rs[0].contact_id == cid
        assert "звіт" in rs[0].text


def test_resume_callback_reenables(client, monkeypatch):
    _admin(monkeypatch)
    from app.core.database import SessionLocal
    from app.modules.contacts.models import Contact, Frequency
    from app.modules.telegram_bot.models import (
        DraftKind, DraftStatus, TelegramDraft,
    )

    with SessionLocal() as db:
        c = Contact(
            first_name="Ігор",
            telegram_chat_id=777,
            contact_frequency=Frequency.monthly,
            auto_reply_paused=True,
        )
        db.add(c)
        db.flush()
        d = TelegramDraft(
            contact_id=c.id, chat_id=777, kind=DraftKind.reply,
            incoming_text="привіт", draft_text="", status=DraftStatus.pending,
        )
        db.add(d)
        db.commit()
        did, cid = d.id, c.id

    fake = FakeClient()
    dispatch(
        fake,
        {"update_id": 2, "callback_query": {"id": "cb", "data": f"d:r:{did}",
         "message": {"chat": {"id": 42}, "message_id": 10}}},
    )
    with SessionLocal() as db:
        assert db.get(Contact, cid).auto_reply_paused is False
