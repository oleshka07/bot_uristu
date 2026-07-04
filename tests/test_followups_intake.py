"""Follow-up cycle, birthday priority, voice intake, NL-search fallback,
pre-meeting brief rendering."""

from datetime import date, datetime, timedelta, timezone

from app.modules.telegram_bot import service
from app.modules.telegram_bot.handlers import dispatch

from test_outreach_queue import _seed_connection, _seed_due_contact
from test_telegram_bot import FakeClient


def _add_msg(db, contact_id: int, direction: str, days_ago: int):
    from app.modules.interactions.models import Channel, Direction, Interaction

    db.add(
        Interaction(
            contact_id=contact_id,
            occurred_at=datetime.now(timezone.utc) - timedelta(days=days_ago),
            channel=Channel.message,
            direction=Direction(direction),
            summary="msg",
            source="telegram",
        )
    )
    db.commit()


def test_followup_prioritized_over_ordinary_overdue(client):
    from app.core.database import SessionLocal

    with SessionLocal() as db:
        _seed_due_contact(db, "Overdue", 101, days_ago=300)
        waiting = _seed_due_contact(db, "Waiting", 102, days_ago=40)
        # Our unanswered outbound message 6 days ago → follow-up candidate.
        _add_msg(db, waiting, "outbound", days_ago=6)

        nxt = service.next_outreach_contact(db)
        assert nxt is not None
        contact, reason = nxt
        assert contact.first_name == "Waiting"
        assert "відповіді не було" in reason


def test_no_double_followup(client):
    from app.core.database import SessionLocal

    with SessionLocal() as db:
        cid = _seed_due_contact(db, "Nagged", 103, days_ago=40)
        # Two consecutive unanswered outbound messages → already nudged once.
        _add_msg(db, cid, "outbound", days_ago=10)
        _add_msg(db, cid, "outbound", days_ago=6)

        nxt = service.next_outreach_contact(db)
        # Falls back to ordinary overdue reason, not another follow-up nag.
        assert nxt is not None
        _, reason = nxt
        assert "відповіді не було" not in reason


def test_birthday_beats_everything(client):
    from app.core.database import SessionLocal
    from app.modules.contacts.models import Contact

    with SessionLocal() as db:
        waiting = _seed_due_contact(db, "Waiting", 104, days_ago=40)
        _add_msg(db, waiting, "outbound", days_ago=6)
        bday = _seed_due_contact(db, "Birthday", 105, days_ago=200)
        c = db.get(Contact, bday)
        today = datetime.now(timezone.utc).date()
        c.birth_date = date(1990, today.month, today.day)
        db.commit()

        nxt = service.next_outreach_contact(db)
        contact, reason = nxt
        assert contact.first_name == "Birthday"
        assert "день народження" in reason


def test_apply_intake_creates_contact_with_facts_and_note(client):
    from app.core.database import SessionLocal

    parsed = {
        "name": "Андрій Фінтех",
        "first_name": "Андрій",
        "last_name": "Фінтех",
        "company": "PayFlow",
        "position": "CEO",
        "note": "Познайомились на івенті, скинути презентацію",
        "facts": [
            {"fact_type": "employer", "value": "Керує PayFlow"},
            {"fact_type": "interest", "value": "Кайтсерфінг"},
        ],
    }
    with SessionLocal() as db:
        contact, created, facts_added = service.apply_intake(db, parsed)
        assert created is True
        assert facts_added == 2
        assert contact.company == "PayFlow"
        assert "скинути презентацію" in contact.notes
        assert {f.value for f in contact.facts} == {"Керує PayFlow", "Кайтсерфінг"}

        # Same name again → updates, not a duplicate.
        contact2, created2, _ = service.apply_intake(
            db, {**parsed, "note": "Друга зустріч"}
        )
        assert created2 is False and contact2.id == contact.id
        assert "Друга зустріч" in contact2.notes


def test_plain_text_message_searches_network(client, monkeypatch):
    monkeypatch.setattr(
        "app.core.config.settings.telegram_chat_id", "42", raising=False
    )
    from app.core.database import SessionLocal
    from app.modules.contacts.models import Contact

    with SessionLocal() as db:
        db.add(Contact(first_name="Kite", company="SurfCo"))
        db.commit()

    fake = FakeClient()
    dispatch(
        fake,
        {"update_id": 1, "message": {"chat": {"id": 42}, "text": "surf"}},
    )
    # No AI in tests → substring fallback still finds the contact.
    reply = fake.sent[-1]["text"]
    assert "Kite" in reply


def test_brief_formatting(client):
    from app.core.database import SessionLocal
    from app.modules.automation.briefs import format_brief
    from app.modules.contacts.models import Contact

    with SessionLocal() as db:
        c = Contact(first_name="Olha", company="Acme", position="CTO", email="o@a.com")
        db.add(c)
        db.commit()
        db.refresh(c)
        event = {
            "id": "ev1",
            "summary": "Синк по проєкту",
            "start": datetime.now(timezone.utc) + timedelta(hours=1),
            "attendee_emails": ["o@a.com"],
            "meet_link": "https://meet.google.com/xyz",
        }
        text = format_brief(event, [c])
        assert "Синк по проєкту" in text
        assert "Olha" in text and "CTO · Acme" in text
        assert "meet.google.com" in text


def test_closer_message_logged_but_not_drafted(client, monkeypatch):
    monkeypatch.setattr(
        "app.core.config.settings.telegram_chat_id", "42", raising=False
    )
    from app.core.database import SessionLocal
    from sqlalchemy import select
    from app.modules.contacts.models import Contact
    from app.modules.telegram_bot.models import TelegramDraft
    from test_telegram_bot import _business_update

    fake = FakeClient()
    update = _business_update(chat_id=555100, text="Ок, дякую! 🙏", msg_id=71)
    dispatch(fake, update)

    from app.core.database import SessionLocal

    with SessionLocal() as db:
        c = db.scalar(select(Contact).where(Contact.telegram_chat_id == 555100))
        assert c is not None and len(c.interactions) == 1  # logged for history
        assert db.scalar(select(TelegramDraft)) is None    # but no draft
    assert fake.sent == []  # and no admin preview — silence is golden


def test_card_deleted_after_skip(client, monkeypatch):
    monkeypatch.setattr(
        "app.core.config.settings.telegram_chat_id", "42", raising=False
    )
    from app.core.database import SessionLocal
    from sqlalchemy import select
    from app.modules.telegram_bot.models import TelegramDraft
    from test_outreach_queue import _seed_connection, _seed_due_contact

    with SessionLocal() as db:
        _seed_connection(db)
        _seed_due_contact(db, "Znyk", 556000, days_ago=90)

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
                "data": f"d:k:{d_id}",
                "message": {"chat": {"id": 42}, "message_id": d_admin, "text": "card"},
            },
        },
    )
    assert {"chat_id": 42, "message_id": d_admin} in fake.deleted


def test_contact_link_prefers_username(client):
    from app.core.database import SessionLocal
    from app.modules.contacts.models import Contact
    from app.modules.telegram_bot.handlers import _contact_link

    with SessionLocal() as db:
        c = Contact(first_name="Ліза", telegram="@koshelizik", telegram_chat_id=1)
        db.add(c); db.commit(); db.refresh(c)
        assert 'href="https://t.me/koshelizik"' in _contact_link(c)

        c2 = Contact(first_name="БезЮзернейма", telegram_chat_id=77)
        db.add(c2); db.commit(); db.refresh(c2)
        assert 'tg://user?id=77' in _contact_link(c2)


def test_channels_reply_saves_parsed_channels(client, monkeypatch):
    monkeypatch.setattr(
        "app.core.config.settings.telegram_chat_id", "42", raising=False
    )
    from app.core.database import SessionLocal
    from sqlalchemy import select
    from app.modules.telegram_bot.models import TelegramDraft
    from test_outreach_queue import _seed_connection, _seed_due_contact

    with SessionLocal() as db:
        _seed_connection(db)
        cid = _seed_due_contact(db, "Kanaly", 557000, days_ago=90)

    fake = FakeClient()
    dispatch(fake, {"update_id": 1, "callback_query": {"id": "cb", "data": "q:start"}})
    with SessionLocal() as db:
        d_id = db.scalar(select(TelegramDraft)).id

    # Press 📇 Контакти → channels message arrives; remember its id.
    dispatch(
        fake,
        {"update_id": 2, "callback_query": {"id": "cb2", "data": f"d:c:{d_id}", "message": {}}},
    )
    channels_msg_id = fake.sent[-1]["message_id"] if "message_id" in fake.sent[-1] else None
    # FakeClient.send_message returns message_id via result; find it in mapping:
    from app.modules.telegram_bot.handlers import _channel_msgs
    channels_msg_id = next(iter(_channel_msgs))

    # Reply with an instagram link + email + phone.
    dispatch(
        fake,
        {
            "update_id": 3,
            "message": {
                "chat": {"id": 42},
                "message_id": 999,
                "reply_to_message": {"message_id": channels_msg_id},
                "text": "instagram.com/kanaly.ig kanaly@mail.com +420777123456",
            },
        },
    )
    with SessionLocal() as db:
        from app.modules.contacts.models import Contact
        c = db.get(Contact, cid)
        assert c.instagram_url == "https://instagram.com/kanaly.ig"
        assert c.email == "kanaly@mail.com"
        assert c.phone == "+420777123456"
    assert any("Зберіг" in s["text"] for s in fake.sent)


def test_importance_orders_queue(client):
    from app.core.database import SessionLocal
    from test_outreach_queue import _seed_due_contact
    from app.modules.telegram_bot import service as svc

    with SessionLocal() as db:
        shallow = _seed_due_contact(db, "Odnorazovy", 558001, days_ago=300)
        deep = _seed_due_contact(db, "Blyzkyi", 558002, days_ago=60)
        # Deep dialogue history → derived importance beats bigger overdue.
        for i in range(20):
            _add_msg(db, deep, "inbound" if i % 2 else "outbound", days_ago=70 + i)

        nxt = svc.next_outreach_contact(db)
        assert nxt is not None
        contact, _ = nxt
        assert contact.first_name == "Blyzkyi"


class _ChatClient(FakeClient):
    """FakeClient that answers getChat with canned profiles by chat_id."""

    def __init__(self, profiles):
        super().__init__()
        self.profiles = profiles

    def get_chat(self, chat_id):
        return self.profiles.get(chat_id)


def test_enrich_from_telegram_fills_username_and_birthday(client):
    from app.core.database import SessionLocal
    from app.modules.telegram_bot import service
    from app.modules.contacts.models import Contact

    with SessionLocal() as db:
        c = Contact(first_name="Владислава", telegram_chat_id=90001)
        db.add(c); db.commit(); db.refresh(c)

        cl = _ChatClient({
            90001: {
                "id": 90001,
                "username": "Vladislavaklim",
                "bio": "Будую і надихаю",
                "birthdate": {"day": 7, "month": 3, "year": 1979},
            }
        })
        changed = service.enrich_from_telegram(db, cl, c)
        assert changed is True
        db.refresh(c)
        assert c.telegram == "@Vladislavaklim"
        assert c.birth_date.day == 7 and c.birth_date.month == 3
        assert c.notes == "Будую і надихаю"


def test_incoming_message_backfills_username_on_export_contact(client, monkeypatch):
    monkeypatch.setattr(
        "app.core.config.settings.telegram_chat_id", "42", raising=False
    )
    from app.core.database import SessionLocal
    from sqlalchemy import select
    from app.modules.contacts.models import Contact
    from test_telegram_bot import _business_update

    with SessionLocal() as db:
        # Export-imported contact: chat_id known, no username → not clickable.
        db.add(Contact(first_name="Владислава", telegram_chat_id=555001))
        db.commit()

    fake = FakeClient()
    dispatch(fake, _business_update(chat_id=555001, text="Привіт, є хвилинка?", msg_id=5))

    with SessionLocal() as db:
        c = db.scalar(select(Contact).where(Contact.telegram_chat_id == 555001))
        # Username captured live from the incoming update → now clickable.
        assert c.telegram == "@oleh_test"


def test_enrich_command_reports_progress(client, monkeypatch):
    monkeypatch.setattr(
        "app.core.config.settings.telegram_chat_id", "42", raising=False
    )
    from app.core.database import SessionLocal
    from app.modules.contacts.models import Contact

    with SessionLocal() as db:
        db.add(Contact(first_name="A", telegram_chat_id=91001))
        db.add(Contact(first_name="B", telegram_chat_id=91002))
        db.commit()

    cl = _ChatClient({
        91001: {"id": 91001, "username": "aaa"},
        91002: {"id": 91002},  # no username available
    })
    dispatch(cl, {"update_id": 1, "message": {"chat": {"id": 42}, "text": "/enrich"}})
    assert any("Оновив 1" in s["text"] for s in cl.sent)

    from sqlalchemy import select
    with SessionLocal() as db:
        a = db.scalar(select(Contact).where(Contact.telegram_chat_id == 91001))
        assert a.telegram == "@aaa"


def test_legacy_chater_button_clears_keyboard(client, monkeypatch):
    monkeypatch.setattr(
        "app.core.config.settings.telegram_chat_id", "42", raising=False
    )
    fake = FakeClient()
    dispatch(
        fake,
        {"update_id": 1, "message": {"chat": {"id": 42}, "text": "📊 Огляд"}},
    )
    sent = fake.sent[-1]
    assert sent.get("reply_markup", {}).get("remove_keyboard") is True
    assert "Chater" in sent["text"]
    # It must NOT be treated as a network-search query.
    assert "🔎" not in sent["text"]
