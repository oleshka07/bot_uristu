"""Задачі в Google Календарі: дзеркалення в Google Tasks і галочка назад."""

from datetime import date, timedelta

import pytest

from app.core.database import SessionLocal
from app.modules.tasks import gsync
from app.modules.tasks.models import Task, TaskStatus
from app.modules.telegram_bot import handlers


@pytest.fixture
def google(monkeypatch):
    """Підмінює Google Tasks: тримає стан списку в памʼяті."""
    from app.modules.integrations.google import client as g

    state = {
        "connected": True,
        "remote": {},          # id -> тіло задачі в Google
        "calls": [],           # історія upsert-ів, щоб перевіряти що саме шлемо
        "next_id": 0,
        "fail_on": None,       # назва задачі, на якій upsert має впасти
    }

    def ensure_tasklist(db, title=None):
        return "list-1" if state["connected"] else None

    def list_google_tasks(db, tasklist_id):
        return [{"id": tid, **body} for tid, body in state["remote"].items()]

    def upsert(db, tasklist_id, *, task_id, title, notes, due, completed):
        if state["fail_on"] == title:
            raise RuntimeError("Google послав")
        state["calls"].append(
            {"task_id": task_id, "title": title, "notes": notes, "due": due,
             "completed": completed}
        )
        if not task_id:
            state["next_id"] += 1
            task_id = f"g{state['next_id']}"
        state["remote"][task_id] = {
            "title": title,
            "notes": notes,
            "due": due,
            "status": "completed" if completed else "needsAction",
        }
        return task_id

    monkeypatch.setattr(g, "ensure_tasklist", ensure_tasklist)
    monkeypatch.setattr(g, "list_google_tasks", list_google_tasks)
    monkeypatch.setattr(g, "upsert_google_task", upsert)
    return state


def _task(title="Подзвонити в банк", **kw):
    with SessionLocal() as db:
        from app.modules.tasks.service import new_uid

        kw.setdefault("due_date", date.today() + timedelta(days=1))
        task = Task(uid=new_uid(), title=title, **kw)
        db.add(task)
        db.commit()
        return task.id


def _get(task_pk: int) -> Task:
    with SessionLocal() as db:
        return db.get(Task, task_pk)


def test_task_with_a_date_appears_in_google(client, google):
    task_pk = _task()
    with SessionLocal() as db:
        report = gsync.sync(db)

    assert report["pushed"] == 1
    assert _get(task_pk).google_task_id == "g1"
    call = google["calls"][0]
    assert call["title"] == "Подзвонити в банк"
    # Google бере з поля due лише дату, тож шлемо опівніч UTC.
    assert call["due"].endswith("T00:00:00.000Z")
    assert call["completed"] is False


def test_task_without_a_date_syncs_but_carries_no_due(client, google):
    _task("Без дати", due_date=None)
    with SessionLocal() as db:
        gsync.sync(db)
    assert google["calls"][0]["due"] is None


def test_renaming_here_reaches_google_on_the_next_pass(client, google):
    task_pk = _task()
    with SessionLocal() as db:
        gsync.sync(db)
        db.get(Task, task_pk).title = "Подзвонити в банк про ліміт"
        db.commit()
        gsync.sync(db)

    last = google["calls"][-1]
    assert last["task_id"] == "g1"          # оновлення, а не дубль
    assert last["title"] == "Подзвонити в банк про ліміт"
    assert len(google["remote"]) == 1


def test_project_and_counterpart_go_into_notes(client, google):
    _task(project="Rozum", counterpart="Марія", notes="деталі")
    with SessionLocal() as db:
        gsync.sync(db)
    notes = google["calls"][0]["notes"]
    assert "Проєкт: Rozum" in notes and "Хто: Марія" in notes and "деталі" in notes


def test_ticking_it_off_on_the_phone_closes_the_task_here(client, google):
    task_pk = _task()
    with SessionLocal() as db:
        gsync.sync(db)
    google["remote"]["g1"]["status"] = "completed"

    with SessionLocal() as db:
        report = gsync.sync(db)

    assert report["completed_from_google"] == 1
    assert _get(task_pk).status == TaskStatus.done


def test_closing_it_here_marks_it_completed_in_google_without_deleting(client, google):
    task_pk = _task()
    with SessionLocal() as db:
        gsync.sync(db)
        db.get(Task, task_pk).status = TaskStatus.done
        db.commit()
        gsync.sync(db)

    # Історія має лишатися видимою в обох місцях.
    assert google["remote"]["g1"]["status"] == "completed"
    assert _get(task_pk).google_task_id == "g1"


def test_deleting_in_google_does_not_resurrect_it(client, google):
    task_pk = _task()
    with SessionLocal() as db:
        gsync.sync(db)
    google["remote"].clear()

    with SessionLocal() as db:
        report = gsync.sync(db)
    assert report["unlinked"] == 1

    task = _get(task_pk)
    assert task.google_sync is False
    assert task.google_task_id is None
    assert task.status != TaskStatus.done   # нашу задачу не чіпали

    # Наступний прохід її туди не повертає.
    with SessionLocal() as db:
        again = gsync.sync(db)
    assert again["pushed"] == 0
    assert google["remote"] == {}


def test_deleted_task_is_out_of_the_sync(client, google):
    from datetime import datetime, timezone

    task_pk = _task()
    with SessionLocal() as db:
        db.get(Task, task_pk).deleted_at = datetime.now(timezone.utc)
        db.commit()
        assert gsync.sync(db)["pushed"] == 0
    assert google["calls"] == []


def test_one_broken_task_does_not_stop_the_rest(client, google):
    google["fail_on"] = "Проблемна"
    _task("Проблемна")
    _task("Нормальна")

    with SessionLocal() as db:
        report = gsync.sync(db)

    assert report["pushed"] == 1
    assert [c["title"] for c in google["calls"]] == ["Нормальна"]


def test_without_google_the_sync_is_a_quiet_no_op(client, google):
    google["connected"] = False
    task_pk = _task()
    with SessionLocal() as db:
        assert gsync.sync(db) == {"skipped": "google not connected"}
    assert _get(task_pk).google_task_id is None


def test_api_endpoint_returns_the_numbers(client, google):
    _task()
    report = client.post("/api/tasks/gsync").json()
    assert report["pushed"] == 1
    assert report["completed_from_google"] == 0


class FakeClient:
    def __init__(self):
        self.messages = []

    def send_message(self, chat, text, **kw):
        self.messages.append(text)


def test_bot_command_reports_the_result(client, google, monkeypatch):
    monkeypatch.setattr(handlers, "_admin_id", lambda: 42)
    bot = FakeClient()
    _task()

    handlers._handle_command(bot, 42, "/gsync")
    assert "надіслано 1" in bot.messages[-1]

    google["connected"] = False
    handlers._handle_command(bot, 42, "/gsync")
    assert "Google не підключений" in bot.messages[-1]
