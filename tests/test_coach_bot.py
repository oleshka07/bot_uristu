"""Бот: питання коуча, відповідь на нього і команди /goals та /goal."""

import pytest

from app.core.database import SessionLocal
from app.modules.coach import service as coach
from app.modules.goals.models import Goal, GoalStatus
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


def _goal(title="Прочитати 25 книг", **kw):
    with SessionLocal() as db:
        kw.setdefault("status", GoalStatus.in_progress)
        kw.setdefault("priority", 60)
        goal = Goal(title=title, **kw)
        db.add(goal)
        db.commit()
        return goal.id


def test_reply_to_an_open_question_updates_the_goal(client, bot, monkeypatch):
    from app.modules.insights import ai

    monkeypatch.setattr(ai, "coach_question", lambda *a, **kw: "Що по книгах?")
    monkeypatch.setattr(
        ai, "coach_review",
        lambda *a, **kw: {"summary": "дві книги", "status": "almost", "reply": "Мало."},
    )
    goal_id = _goal()
    with SessionLocal() as db:
        coach.open_question(db)

    assert handlers._handle_coach_answer(bot, 42, "прочитав дві") is True
    assert "Мало." in bot.messages[-1]
    with SessionLocal() as db:
        goal = db.get(Goal, goal_id)
        assert goal.status == "almost"
        assert "дві книги" in goal.coach_notes


def test_without_an_open_question_the_message_flows_on(client, bot):
    _goal()
    assert handlers._handle_coach_answer(bot, 42, "хто з моїх у крипті?") is False
    assert bot.messages == []


def test_calendar_request_is_not_swallowed_as_an_answer(client, bot, monkeypatch):
    from app.modules.insights import ai

    monkeypatch.setattr(ai, "coach_question", lambda *a, **kw: "Що по книгах?")
    _goal()
    with SessionLocal() as db:
        coach.open_question(db)

    # Питання висить, але це явно прохання про зустріч — його чіпати не можна.
    assert handlers._handle_coach_answer(bot, 42, "додай зустріч завтра о 15:00") is False
    assert bot.messages == []


def test_goals_command_shows_the_tracker(client, bot):
    _goal("Аудит AI", area="work", coach_notes="01.05.26: почав")
    _goal("Книги", area="pers")
    handlers._handle_command(bot, 42, "/goals")
    text = bot.messages[-1]
    assert "Аудит AI" in text and "Книги" in text
    assert "in progress" in text
    assert "без записів" in text  # ціль, якої коуч ще не торкався


def test_goal_command_reports_when_nothing_to_ask(client, bot):
    handlers._handle_command(bot, 42, "/goal")
    assert "нема про що" in bot.messages[-1].lower()
