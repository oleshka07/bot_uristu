"""GTD stalled-project check: an active project with no doable next action."""

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
    from app.modules.projects import service as proj
    from app.modules.projects.models import ProjectStatus
    from app.modules.tasks.models import Task, TaskKind, TaskStatus
    from app.modules.tasks.service import new_uid

    healthy = proj.create(db, "Живий проєкт")
    empty = proj.create(db, "Порожній проєкт")
    waiting = proj.create(db, "Чекаю на інших")
    paused = proj.create(db, "На паузі")
    paused.status = ProjectStatus.paused

    db.add(
        Task(uid=new_uid(), title="зробити крок", project_id=healthy.id,
             status=TaskStatus.todo, kind=TaskKind.task)
    )
    # only a blocked task → nothing doable
    db.add(
        Task(uid=new_uid(), title="чекаю відповідь", project_id=waiting.id,
             status=TaskStatus.hold, kind=TaskKind.task)
    )
    # done tasks don't keep a project alive
    db.add(
        Task(uid=new_uid(), title="вже зробив", project_id=empty.id,
             status=TaskStatus.done, kind=TaskKind.task)
    )
    db.commit()
    return healthy, empty, waiting, paused


def test_stalled_detection(client):
    from app.core.database import SessionLocal
    from app.modules.projects import service as proj

    with SessionLocal() as db:
        healthy, empty, waiting, paused = _seed(db)
        names = {p.name: reason for p, reason in proj.stalled_projects(db)}

    assert names.get("Порожній проєкт") == "empty"
    assert names.get("Чекаю на інших") == "waiting"
    assert "Живий проєкт" not in names      # has a doable next action
    assert "На паузі" not in names          # parked on purpose, not stalled


def test_stalled_command(client, monkeypatch):
    _admin(monkeypatch)
    from app.core.database import SessionLocal

    with SessionLocal() as db:
        _seed(db)

    fake = FakeClient()
    dispatch(fake, _msg("/stalled"))
    txt = fake.sent[-1]["text"]
    assert "без наступної дії" in txt.lower()
    assert "Порожній проєкт" in txt and "Чекаю на інших" in txt
    assert "Живий проєкт" not in txt


def test_stalled_command_all_clear(client, monkeypatch):
    _admin(monkeypatch)
    fake = FakeClient()
    dispatch(fake, _msg("/stalled"))
    assert "є наступна дія" in fake.sent[-1]["text"]
