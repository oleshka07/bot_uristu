"""Bot: /next, /tasks and the ✓/▶ buttons under a task."""

import pytest

from app.modules.telegram_bot import handlers


class FakeClient:
    def __init__(self):
        self.messages = []
        self.answers = []

    def send_message(self, chat, text, **kw):
        self.messages.append((text, kw.get("reply_markup")))

    def answer_callback(self, cb_id, text=None):
        self.answers.append(text)


@pytest.fixture
def bot(monkeypatch):
    client = FakeClient()
    monkeypatch.setattr(handlers, "_admin_id", lambda: 42)
    return client


def test_next_shows_top_task_with_buttons(client, bot):
    client.post("/api/tasks", json={"title": "Звіт", "duration_min": 180})
    client.post("/api/tasks", json={"title": "Дзвінок", "duration_min": 5})

    handlers._handle_command(bot, 42, "/next")
    text, markup = bot.messages[-1]
    assert "Дзвінок" in text                      # коротша — перша
    assert "5 хв" in text
    buttons = markup["inline_keyboard"][0]
    assert [b["text"] for b in buttons] == ["✓ Готово", "▶ Взяв у роботу"]


def test_done_button_closes_task_and_offers_next(client, bot):
    client.post("/api/tasks", json={"title": "Дзвінок", "duration_min": 5})
    client.post("/api/tasks", json={"title": "Лист", "duration_min": 8})
    first = client.get("/api/tasks").json()[0]

    handlers._handle_task_callback(bot, "cb1", f"tk:done:{first['id']}", 42)

    assert bot.answers == ["✓ Готово"]
    text, _ = bot.messages[-1]
    assert "Готово: Дзвінок" in text and "Лист" in text
    # Закрита задача зникає зі списку.
    assert [t["title"] for t in client.get("/api/tasks").json()] == ["Лист"]


def test_last_task_done_says_no_more(client, bot):
    t = client.post("/api/tasks", json={"title": "Єдина"}).json()
    handlers._handle_task_callback(bot, "cb2", f"tk:done:{t['id']}", 42)
    assert "Більше задач немає" in bot.messages[-1][0]


def test_tasks_list_is_ordered(client, bot):
    client.post("/api/tasks", json={"title": "Довга", "duration_min": 300})
    client.post("/api/tasks", json={"title": "Термінова", "status": "immediate",
                                    "duration_min": 300})
    handlers._handle_command(bot, 42, "/tasks")
    text, _ = bot.messages[-1]
    assert text.index("Термінова") < text.index("Довга")


def test_stale_button_is_ignored(client, bot):
    handlers._handle_task_callback(bot, "cb3", "tk:done:9999", 42)
    assert bot.answers == ["Уже неактуально"]
    assert bot.messages == []
