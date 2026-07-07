"""B2 Reflection — 'Reflect on your relationship with X' (Mesh)."""

from datetime import datetime, timedelta, timezone

from app.modules.telegram_bot.handlers import dispatch

from test_telegram_bot import FakeClient


def _cmd(text: str) -> dict:
    return {"update_id": 1, "message": {"chat": {"id": 42}, "text": text}}


def _seed_drifting(db, name: str, days_ago: int = 200):
    from app import warmth
    from app.modules.contacts.models import Contact, Frequency
    from app.modules.interactions.models import Channel, Direction, Interaction

    c = Contact(first_name=name, contact_frequency=Frequency.monthly, importance=3)
    db.add(c)
    db.flush()
    db.add(
        Interaction(
            contact_id=c.id,
            occurred_at=datetime.now(timezone.utc) - timedelta(days=days_ago),
            channel=Channel.message,
            direction=Direction.outbound,
            summary="давня розмова",
        )
    )
    db.flush()
    db.refresh(c)
    warmth.refresh(c)
    db.commit()
    return c.id


def test_reflect_command_renders_ai_reflection(client, monkeypatch):
    monkeypatch.setattr(
        "app.core.config.settings.telegram_chat_id", "42", raising=False
    )
    from app.core.database import SessionLocal

    with SessionLocal() as db:
        cid = _seed_drifting(db, "Богдан")

    monkeypatch.setattr(
        "app.modules.insights.ai.reflect_on_relationships",
        lambda items: [
            {"contact_id": items[0]["id"], "reflection": "Давно не спілкувались.",
             "action": "Напиши коротке привітання."}
        ],
    )
    fake = FakeClient()
    dispatch(fake, _cmd("/reflect"))
    txt = fake.sent[-1]["text"]
    assert "Богдан" in txt
    assert "Давно не спілкувались" in txt
    assert "Напиши коротке привітання" in txt


def test_reflect_ai_off_is_graceful(client, monkeypatch):
    monkeypatch.setattr(
        "app.core.config.settings.telegram_chat_id", "42", raising=False
    )
    from app.core.database import SessionLocal

    with SessionLocal() as db:
        _seed_drifting(db, "Галина")

    monkeypatch.setattr(
        "app.modules.insights.ai.reflect_on_relationships", lambda items: None
    )
    fake = FakeClient()
    dispatch(fake, _cmd("/reflect"))
    assert "AI недоступний" in fake.sent[-1]["text"]


def test_pick_reflection_prioritises_drifting_important(client):
    from app.core.database import SessionLocal
    from app.modules.automation.reviews import pick_reflection_contacts

    with SessionLocal() as db:
        _seed_drifting(db, "Важливий", days_ago=300)
        picked = pick_reflection_contacts(db, 3)
        assert picked and picked[0].first_name == "Важливий"
