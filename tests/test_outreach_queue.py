"""Outreach queue: due-contact selection, cards, advance-on-action."""

from datetime import datetime, timedelta, timezone

from app.modules.telegram_bot.handlers import dispatch
from app.modules.telegram_bot.models import DraftKind, DraftStatus

from test_telegram_bot import FakeClient


def _seed_due_contact(db, name: str, chat_id: int, days_ago: int = 90):
    from app import warmth
    from app.modules.contacts.models import Contact, Frequency
    from app.modules.interactions.models import Channel, Direction, Interaction

    c = Contact(
        first_name=name,
        contact_frequency=Frequency.monthly,
        telegram_chat_id=chat_id,
    )
    db.add(c)
    db.flush()
    db.add(
        Interaction(
            contact_id=c.id,
            occurred_at=datetime.now(timezone.utc) - timedelta(days=days_ago),
            channel=Channel.message,
            direction=Direction.outbound,
            summary=f"остання розмова з {name}",
        )
    )
    db.flush()
    db.refresh(c)
    warmth.refresh(c)
    db.commit()
    return c.id


def _seed_connection(db):
    from app.modules.telegram_bot.service import upsert_connection

    upsert_connection(db, "bc-queue", 42, True)


def test_queue_start_sends_card_for_most_overdue(client, monkeypatch):
    monkeypatch.setattr(
        "app.core.config.settings.telegram_chat_id", "42", raising=False
    )
    from app.core.database import SessionLocal

    with SessionLocal() as db:
        _seed_connection(db)
        _seed_due_contact(db, "Trohy", 771, days_ago=45)
        _seed_due_contact(db, "Duzhe", 772, days_ago=200)  # most overdue

    fake = FakeClient()
    dispatch(fake, {"update_id": 1, "callback_query": {"id": "cb", "data": "q:start"}})

    card = fake.sent[-1]
    assert card["chat_id"] == 42
    assert "Duzhe" in card["text"]          # most overdue first
    assert "Чому зараз" in card["text"]     # the explanation line
    assert "остання розмова" in card["text"]

    with SessionLocal() as db:
        from sqlalchemy import select
        from app.modules.telegram_bot.models import TelegramDraft

        draft = db.scalar(select(TelegramDraft))
        assert draft.kind == DraftKind.outreach
        assert draft.chat_id == 772
        assert draft.business_connection_id == "bc-queue"


def test_queue_advances_after_skip_and_finishes(client, monkeypatch):
    monkeypatch.setattr(
        "app.core.config.settings.telegram_chat_id", "42", raising=False
    )
    from app.core.database import SessionLocal
    from sqlalchemy import select
    from app.modules.telegram_bot.models import TelegramDraft

    with SessionLocal() as db:
        _seed_connection(db)
        _seed_due_contact(db, "Alpha", 881, days_ago=200)
        _seed_due_contact(db, "Beta", 882, days_ago=100)

    fake = FakeClient()
    dispatch(fake, {"update_id": 1, "callback_query": {"id": "cb", "data": "q:start"}})

    with SessionLocal() as db:
        d1 = db.scalar(select(TelegramDraft))
        d1_id, d1_admin = d1.id, d1.admin_message_id

    # Skip the first card → queue auto-advances to Beta.
    dispatch(
        fake,
        {
            "update_id": 2,
            "callback_query": {
                "id": "cb2",
                "data": f"d:k:{d1_id}",
                "message": {"chat": {"id": 42}, "message_id": d1_admin, "text": "card"},
            },
        },
    )
    assert "Beta" in fake.sent[-1]["text"]

    with SessionLocal() as db:
        d2 = db.scalar(
            select(TelegramDraft).where(TelegramDraft.status == DraftStatus.pending)
        )
        d2_id, d2_admin = d2.id, d2.admin_message_id

    # Skip the second too → queue is empty, summary arrives.
    dispatch(
        fake,
        {
            "update_id": 3,
            "callback_query": {
                "id": "cb3",
                "data": f"d:k:{d2_id}",
                "message": {"chat": {"id": 42}, "message_id": d2_admin, "text": "card"},
            },
        },
    )
    assert "Черга на сьогодні порожня" in fake.sent[-1]["text"]


def test_queue_requires_business_connection(client, monkeypatch):
    monkeypatch.setattr(
        "app.core.config.settings.telegram_chat_id", "42", raising=False
    )
    from app.core.database import SessionLocal

    with SessionLocal() as db:
        _seed_due_contact(db, "Solo", 991, days_ago=90)  # no connection seeded

    fake = FakeClient()
    dispatch(fake, {"update_id": 1, "callback_query": {"id": "cb", "data": "q:start"}})
    assert "Business-з'єднання" in fake.sent[-1]["text"]


def test_digest_command_has_queue_button(client, monkeypatch):
    monkeypatch.setattr(
        "app.core.config.settings.telegram_chat_id", "42", raising=False
    )
    fake = FakeClient()
    dispatch(
        fake,
        {
            "update_id": 1,
            "message": {"chat": {"id": 42}, "text": "/today"},
        },
    )
    digest = fake.sent[-1]
    kb = digest.get("reply_markup") or {}
    assert kb.get("inline_keyboard", [[]])[0][0]["callback_data"] == "q:start"


def test_stop_list_button_excludes_contact_and_advances(client, monkeypatch):
    monkeypatch.setattr(
        "app.core.config.settings.telegram_chat_id", "42", raising=False
    )
    from app.core.database import SessionLocal
    from sqlalchemy import select
    from app.modules.contacts.models import Contact
    from app.modules.telegram_bot.models import TelegramDraft

    with SessionLocal() as db:
        _seed_connection(db)
        cid = _seed_due_contact(db, "Odnorazovyi", 551, days_ago=300)

    fake = FakeClient()
    dispatch(fake, {"update_id": 1, "callback_query": {"id": "cb", "data": "q:start"}})

    with SessionLocal() as db:
        d = db.scalar(select(TelegramDraft))
        d_id, d_admin = d.id, d.admin_message_id

    dispatch(
        fake,
        {
            "update_id": 2,
            "callback_query": {
                "id": "cb2",
                "data": f"d:x:{d_id}",
                "message": {"chat": {"id": 42}, "message_id": d_admin, "text": "card"},
            },
        },
    )

    with SessionLocal() as db:
        c = db.get(Contact, cid)
        assert c.do_not_contact is True
        # Queue advanced and, with nobody left, reported it's done.
        assert "Черга на сьогодні порожня" in fake.sent[-1]["text"]
        # Stop-listed contact never reappears in the queue.
        from app.modules.telegram_bot import service as svc

        assert svc.next_outreach_contact(db) is None


def test_contacts_button_lists_channels_with_copyable_draft(client, monkeypatch):
    monkeypatch.setattr(
        "app.core.config.settings.telegram_chat_id", "42", raising=False
    )
    from app.core.database import SessionLocal
    from sqlalchemy import select
    from app.modules.contacts.models import Contact
    from app.modules.telegram_bot.models import TelegramDraft
    from app.modules.telegram_bot import service as svc

    with SessionLocal() as db:
        _seed_connection(db)
        cid = _seed_due_contact(db, "Multi", 661, days_ago=90)
        c = db.get(Contact, cid)
        c.email = "multi@example.com"
        c.instagram_url = "https://instagram.com/multi"
        db.commit()

    fake = FakeClient()
    dispatch(fake, {"update_id": 1, "callback_query": {"id": "cb", "data": "q:start"}})

    with SessionLocal() as db:
        d = db.scalar(select(TelegramDraft))
        svc.update_draft_text(db, d, "Привіт!")
        d_id = d.id

    dispatch(
        fake,
        {
            "update_id": 2,
            "callback_query": {"id": "cb2", "data": f"d:c:{d_id}", "message": {}},
        },
    )
    channels = fake.sent[-1]["text"]
    assert "multi@example.com" in channels
    assert "instagram.com/multi" in channels
    assert "<code>Привіт!</code>" in channels

    # The card is still pending — contacts view is informational.
    with SessionLocal() as db:
        d = db.get(TelegramDraft, d_id)
        assert d.status == DraftStatus.pending


def test_translate_without_ai_keeps_draft(client, monkeypatch):
    monkeypatch.setattr(
        "app.core.config.settings.telegram_chat_id", "42", raising=False
    )
    from app.core.database import SessionLocal
    from sqlalchemy import select
    from app.modules.telegram_bot.models import TelegramDraft
    from app.modules.telegram_bot import service as svc

    with SessionLocal() as db:
        _seed_connection(db)
        _seed_due_contact(db, "Lang", 662, days_ago=90)

    fake = FakeClient()
    dispatch(fake, {"update_id": 1, "callback_query": {"id": "cb", "data": "q:start"}})

    with SessionLocal() as db:
        d = db.scalar(select(TelegramDraft))
        svc.update_draft_text(db, d, "Оригінал")
        d_id = d.id

    dispatch(
        fake,
        {
            "update_id": 2,
            "callback_query": {"id": "cb2", "data": f"d:t:{d_id}:en", "message": {}},
        },
    )
    # No ANTHROPIC key in tests → translation fails gracefully, draft intact.
    assert "Не вдалося перекласти" in fake.callbacks
    with SessionLocal() as db:
        assert db.get(TelegramDraft, d_id).draft_text == "Оригінал"
