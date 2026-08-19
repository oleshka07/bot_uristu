"""GTD contexts: 'what can I actually do right now, here'."""

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
    from app.modules.tasks.models import Task, TaskKind, TaskStatus
    from app.modules.tasks.service import new_uid

    db.add(Task(uid=new_uid(), title="Подзвонити в банк", tags="@дзвінки",
                status=TaskStatus.todo, kind=TaskKind.task))
    db.add(Task(uid=new_uid(), title="Дозвонитись Роману", item_type="дзвінок",
                status=TaskStatus.todo, kind=TaskKind.task))
    db.add(Task(uid=new_uid(), title="Купити картридж", tags="@місто",
                status=TaskStatus.todo, kind=TaskKind.task))
    db.add(Task(uid=new_uid(), title="Без контексту",
                status=TaskStatus.todo, kind=TaskKind.task))
    db.commit()


def test_normalize_and_derive():
    from app.modules.tasks import service as ts
    from app.modules.tasks.models import Task

    assert ts.normalize_context("дзвінки") == "@дзвінки"
    assert ts.normalize_context("@Телефон") == "@дзвінки"
    assert ts.normalize_context("call") == "@дзвінки"
    assert ts.normalize_context("@клієнти") == "@клієнти"   # ad-hoc kept
    assert ts.normalize_context("") is None

    # item_type alone gives a context, no tagging needed
    t = Task(uid="x", title="t", item_type="дзвінок")
    assert "@дзвінки" in ts.task_contexts(t)


def test_contexts_listing_and_filtering(client):
    from app.core.database import SessionLocal
    from app.modules.tasks import service as ts

    with SessionLocal() as db:
        _seed(db)
        counts = ts.list_contexts(db)
        assert counts.get("@дзвінки") == 2      # tag + derived from item_type
        assert counts.get("@місто") == 1
        titles = [t.title for t in ts.tasks_in_context(db, "дзвінки")]
        assert "Подзвонити в банк" in titles and "Дозвонитись Роману" in titles
        assert "Купити картридж" not in titles


def test_bot_contexts_and_next_in_context(client, monkeypatch):
    _admin(monkeypatch)
    from app.core.database import SessionLocal

    with SessionLocal() as db:
        _seed(db)

    fake = FakeClient()
    dispatch(fake, _msg("/contexts"))
    assert "@дзвінки" in fake.sent[-1]["text"]

    dispatch(fake, _msg("/next @дзвінки"))
    txt = fake.sent[-1]["text"]
    assert "@дзвінки" in txt
    assert "Купити картридж" not in txt

    dispatch(fake, _msg("/tasks @місто"))
    assert "Купити картридж" in fake.sent[-1]["text"]


def test_empty_context_message(client, monkeypatch):
    _admin(monkeypatch)
    fake = FakeClient()
    dispatch(fake, _msg("/next @дзвінки"))
    assert "задач немає" in fake.sent[-1]["text"].lower()
