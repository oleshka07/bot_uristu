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
