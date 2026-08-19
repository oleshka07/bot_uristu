"""One guided weekly ritual instead of three scattered digests."""

from datetime import datetime, timedelta, timezone

from app.modules.telegram_bot.handlers import dispatch

from test_telegram_bot import FakeClient


def _msg(text: str) -> dict:
    return {"update_id": 1, "message": {"chat": {"id": 42}, "text": text}}


def _admin(monkeypatch):
    monkeypatch.setattr(
        "app.core.config.settings.telegram_chat_id", "42", raising=False
    )
    monkeypatch.setattr(
        "app.modules.insights.ai.parse_assistant_intent", lambda text, today: None
    )


def _seed(db):
    from app import warmth
    from app.modules.contacts.models import Contact, Frequency
    from app.modules.ideas import service as ideas
    from app.modules.interactions.models import Channel, Direction, Interaction
    from app.modules.projects import service as proj
    from app.modules.resources import service as res
    from app.modules.tasks.models import Task, TaskKind, TaskStatus
    from app.modules.tasks.service import new_uid

    proj.create(db, "Застряглий проєкт")          # no tasks → stalled
    db.add(Task(uid=new_uid(), title="Зроблена задача", status=TaskStatus.done,
                kind=TaskKind.task))
    db.add(Task(uid=new_uid(), title="Чекаю документи", status=TaskStatus.hold,
                kind=TaskKind.task, counterpart="Роман"))
    c = Contact(first_name="Остиглий", contact_frequency=Frequency.monthly)
    db.add(c)
    db.flush()
    db.add(Interaction(contact_id=c.id, channel=Channel.message,
                       direction=Direction.outbound, summary="давно",
                       occurred_at=datetime.now(timezone.utc) - timedelta(days=200)))
    db.flush()
    db.refresh(c)
    warmth.refresh(c)
    ideas.create_idea(db, "Є ідея зробити маркетплейс")
    res.create_resource(db, url="https://example.com/x", note="подивитись")
    db.commit()


def test_full_review_covers_every_section(client, monkeypatch):
    from app.core.database import SessionLocal
    from app.modules.automation import reviews

    # Google is not connected in tests → calendar section simply absent.
    with SessionLocal() as db:
        _seed(db)
        text = reviews.full_review_text(db)

    assert "Тижневий огляд" in text
    assert "Тиждень позаду" in text and "Закрито задач: <b>1</b>" in text
    assert "Що застрягло" in text
    assert "Застряглий проєкт" in text          # no next action
    assert "Чекаю документи" in text and "Роман" in text
    assert "Люди" in text and "Остиглий" in text
    assert "Подумати" in text and "Ідей: <b>1</b>" in text and "На потім" in text


def test_review_command_sends(client, monkeypatch):
    _admin(monkeypatch)
    from app.core.database import SessionLocal

    with SessionLocal() as db:
        _seed(db)

    fake = FakeClient()
    dispatch(fake, _msg("/review"))
    assert fake.sent and "Тижневий огляд" in fake.sent[0]["text"]
    # every chunk stays under Telegram's 4096 limit
    assert all(len(m["text"]) <= 3800 for m in fake.sent)


def test_quiet_week_stays_short(client):
    from app.core.database import SessionLocal
    from app.modules.automation import reviews

    with SessionLocal() as db:
        text = reviews.full_review_text(db)
    # Empty sections are skipped, so nothing but the header + wrap-up.
    assert "Що застрягло" not in text and "Подумати" not in text
    assert "Тиждень позаду" in text


def test_monday_job_sends_the_full_ritual(client, monkeypatch):
    from app.core.database import SessionLocal
    from app.modules.automation import reviews

    with SessionLocal() as db:
        _seed(db)

    monkeypatch.setattr(
        "app.core.config.settings.weekly_review_enabled", True, raising=False
    )
    monkeypatch.setattr(reviews, "_configured", lambda: True)
    captured = {}

    def _fake_send(text, **kw):
        captured["text"] = text
        return True

    monkeypatch.setattr("app.modules.automation.telegram.send_message", _fake_send)
    assert reviews.run_weekly_review() is True
    assert "Тижневий огляд" in captured["text"]
    assert "Що застрягло" in captured["text"]
