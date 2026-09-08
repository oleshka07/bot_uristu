"""Задачі-нагадування: «впиши задачу X, відповідальний Y, нагадуй раз на місяць»."""

from datetime import datetime, timedelta, timezone

import pytest

from app.core.database import SessionLocal
from app.modules.coach import service as coach
from app.modules.tasks import service as tasks
from app.modules.tasks.models import Task, TaskStatus
from app.modules.telegram_bot import handlers


class FakeClient:
    def __init__(self):
        self.messages = []

    def send_message(self, chat, text, **kw):
        self.messages.append(text)


@pytest.fixture
def bot(monkeypatch):
    monkeypatch.setattr(handlers, "_admin_id", lambda: 42)
    return FakeClient()


@pytest.fixture
def no_ai(monkeypatch):
    """Без AI — працює лише детермінований розбір тексту."""
    from app.modules.insights import ai

    monkeypatch.setattr(ai, "parse_assistant_intent", lambda *a, **kw: None)


@pytest.mark.parametrize(
    "text,expected_days",
    [
        ("нагадуй раз на місяць", 30),
        ("щотижня", 7),
        ("раз на 3 тижні", 21),
        ("раз на квартал", 90),
        ("щороку", 365),
        ("раз на 10 днів", 10),
    ],
)
def test_recurrence_is_read_from_plain_words(text, expected_days):
    parsed = tasks.parse_recur(text)
    assert parsed is not None and parsed[1] == expected_days


def test_text_without_recurrence_returns_nothing():
    assert tasks.parse_recur("оновити прайс") is None
    assert tasks.parse_recur("") is None


def test_capture_creates_the_task_with_owner_and_schedule(client, bot, no_ai):
    handled = handlers._handle_assistant_intent(
        bot, 42, "впиши задачу: оновити прайс, відповідальний Марія, нагадуй раз на місяць"
    )
    assert handled is True

    with SessionLocal() as db:
        task = db.query(Task).one()
        assert task.title == "оновити прайс"
        assert task.counterpart == "Марія"
        assert task.recur_days == 30
        assert task.next_remind_at is not None
        assert coach.pending_checkin(db) is None  # питати нічого, все відомо
    assert "Нагадуватиму" in bot.messages[-1]


def test_missing_recurrence_is_always_asked(client, bot, no_ai):
    handlers._handle_assistant_intent(bot, 42, "впиши задачу: подзвонити в банк")

    with SessionLocal() as db:
        task = db.query(Task).one()
        assert task.recur_days is None
        assert task.next_remind_at is None      # без періодичності нагадувань немає
        pending = coach.pending_checkin(db)
        assert pending is not None and pending.kind == "frequency"
    assert "Як часто нагадувати" in bot.messages[-1]


def test_answering_the_frequency_question_starts_the_schedule(client, bot, no_ai):
    handlers._handle_assistant_intent(bot, 42, "впиши задачу: подзвонити в банк")

    with SessionLocal() as db:
        reply = coach.record_answer(db, "раз на тиждень")
        task = db.query(Task).one()
        assert task.recur_days == 7
        assert task.next_remind_at is not None
    assert "раз на тиждень" in reply


def test_unclear_frequency_keeps_the_question_open(client, bot, no_ai):
    handlers._handle_assistant_intent(bot, 42, "впиши задачу: подзвонити в банк")

    with SessionLocal() as db:
        reply = coach.record_answer(db, "ну колись потім")
        assert "Не зрозумів періодичність" in reply
        assert coach.record_answer(db, "щомісяця") is not None
        assert db.query(Task).one().recur_days == 30


def test_only_due_tasks_are_reminded(client):
    with SessionLocal() as db:
        soon = tasks.create_reminder_task(db, title="ще рано", recur="щотижня", recur_days=7)
        due = tasks.create_reminder_task(db, title="час", recur="щотижня", recur_days=7)
        due.next_remind_at = datetime.now(timezone.utc) - timedelta(hours=1)
        db.commit()

        assert [t.title for t in tasks.due_reminder_tasks(db)] == ["час"]
        assert soon.title not in [t.title for t in tasks.due_reminder_tasks(db)]


def test_paused_task_gets_no_reminders(client):
    with SessionLocal() as db:
        task = tasks.create_reminder_task(db, title="на паузі", recur="щотижня", recur_days=7)
        task.next_remind_at = datetime.now(timezone.utc) - timedelta(hours=1)
        task.status = TaskStatus.hold
        db.commit()
        assert tasks.due_reminder_tasks(db) == []


def test_answer_lands_in_notes_and_moves_the_next_reminder(client):
    with SessionLocal() as db:
        task = tasks.create_reminder_task(db, title="оновити прайс", recur="раз на місяць", recur_days=30)
        task.next_remind_at = datetime.now(timezone.utc) - timedelta(hours=1)
        db.commit()
        coach.open_task_question(db, task, "Що по ній?")

        reply = coach.record_answer(db, "оновив половину позицій")
        db.refresh(task)
        assert task.notes.endswith(": оновив половину позицій")
        assert task.notes.startswith(coach.note_date())
        assert tasks.to_utc(task.next_remind_at) > datetime.now(timezone.utc)
        assert "Записав" in reply


def test_saying_done_closes_the_task(client):
    with SessionLocal() as db:
        task = tasks.create_reminder_task(db, title="подати звіт", recur="щороку", recur_days=365)
        coach.open_task_question(db, task, "Що по ній?")
        reply = coach.record_answer(db, "готово")

        db.refresh(task)
        assert task.status == TaskStatus.done
        assert task.next_remind_at is None
        assert "Закрив" in reply


def test_task_reminder_does_not_consume_the_daily_goal_question(client, monkeypatch):
    """Нагадування по задачі не має закривати питання дня по цілях."""
    from app.modules.goals.models import Goal
    from app.modules.insights import ai

    monkeypatch.setattr(ai, "coach_question", lambda *a, **kw: "Що по цілі?")
    with SessionLocal() as db:
        db.add(Goal(title="Ціль", priority=60, status="in progress"))
        db.commit()
        task = tasks.create_reminder_task(db, title="задача", recur="щотижня", recur_days=7)
        coach.open_task_question(db, task, "Що по задачі?")

        assert coach.asked_today(db) is None      # питання дня ще не ставили
        assert coach.open_question(db) is not None
