"""Natural-language calendar events + simple event reminders (ex-Chater)."""

import datetime as dt

from app.modules.telegram_bot.handlers import dispatch

from test_telegram_bot import FakeClient


def _msg(text: str) -> dict:
    return {"update_id": 1, "message": {"chat": {"id": 42}, "text": text}}


def _calendar_intent(monkeypatch, **payload):
    base = {
        "action": "calendar",
        "person": "",
        "text": "",
        "due_date": "",
        "frequency": "",
        "importance": 0,
        "title": "",
        "start_time": "",
        "end_time": "",
        "attendee_email": "",
        "google_meet": False,
    }
    base.update(payload)
    monkeypatch.setattr(
        "app.modules.insights.ai.parse_assistant_intent",
        lambda text, today: dict(base),
    )


def test_calendar_intent_creates_event(client, monkeypatch):
    monkeypatch.setattr(
        "app.core.config.settings.telegram_chat_id", "42", raising=False
    )
    today = dt.date.today().isoformat()
    _calendar_intent(
        monkeypatch,
        title="Зустріч з Сергієм",
        due_date=today,
        start_time="14:00",
        person="Сергій",
    )
    monkeypatch.setattr(
        "app.integrations.google.status", lambda db: {"connected": True}
    )
    captured = {}

    def _fake_create(db, **kw):
        captured.update(kw)
        return {"summary": kw["summary"], "start": kw["start_local"],
                "html_link": "http://x", "meet_link": None}

    monkeypatch.setattr("app.integrations.google.create_event", _fake_create)

    fake = FakeClient()
    dispatch(fake, _msg("додай зустріч на сьогодні о 14:00 з Сергієм"))
    txt = fake.sent[-1]["text"]
    assert "Подію створено" in txt and "Зустріч з Сергієм" in txt
    assert captured["start_local"].endswith("T14:00:00")
    # default end = +1h
    assert captured["end_local"].endswith("T15:00:00")


def test_calendar_with_meet_and_email(client, monkeypatch):
    monkeypatch.setattr(
        "app.core.config.settings.telegram_chat_id", "42", raising=False
    )
    tomorrow = (dt.date.today() + dt.timedelta(days=1)).isoformat()
    _calendar_intent(
        monkeypatch,
        title="Зустріч з Романом",
        due_date=tomorrow,
        start_time="11:00",
        attendee_email="roman@gmail.com",
        google_meet=True,
    )
    monkeypatch.setattr(
        "app.integrations.google.status", lambda db: {"connected": True}
    )
    monkeypatch.setattr(
        "app.integrations.google.create_event",
        lambda db, **kw: {
            "summary": kw["summary"], "start": kw["start_local"],
            "html_link": "http://x",
            "meet_link": "https://meet.google.com/abc" if kw["add_meet"] else None,
        },
    )
    fake = FakeClient()
    dispatch(fake, _msg("зустріч з Романом завтра 11:00 через Google Meet roman@gmail.com"))
    txt = fake.sent[-1]["text"]
    assert "roman@gmail.com" in txt
    assert "meet.google.com" in txt


def test_calendar_not_connected(client, monkeypatch):
    monkeypatch.setattr(
        "app.core.config.settings.telegram_chat_id", "42", raising=False
    )
    _calendar_intent(
        monkeypatch, title="Подія", due_date=dt.date.today().isoformat(),
        start_time="09:00",
    )
    monkeypatch.setattr(
        "app.integrations.google.status", lambda db: {"connected": False}
    )
    fake = FakeClient()
    dispatch(fake, _msg("додай подію сьогодні о 9"))
    assert "не підключений" in fake.sent[-1]["text"]


def _none_intent(monkeypatch):
    """Simulate the AI under-classifying / failing — everything empty/none."""
    monkeypatch.setattr(
        "app.modules.insights.ai.parse_assistant_intent",
        lambda text, today: {
            "action": "none", "person": "", "text": "", "due_date": "",
            "frequency": "", "importance": 0, "title": "", "start_time": "",
            "end_time": "", "attendee_email": "", "google_meet": False,
        },
    )


def test_calendar_keyword_net_and_text_parsing(client, monkeypatch):
    """Even if the AI says 'none', a calendar phrase is caught and the date/
    time are parsed from the raw text."""
    monkeypatch.setattr(
        "app.core.config.settings.telegram_chat_id", "42", raising=False
    )
    _none_intent(monkeypatch)
    monkeypatch.setattr(
        "app.integrations.google.status", lambda db: {"connected": True}
    )
    captured = {}

    def _fake_create(db, **kw):
        captured.update(kw)
        return {"summary": kw["summary"], "start": kw["start_local"],
                "html_link": "http://x", "meet_link": None}

    monkeypatch.setattr("app.integrations.google.create_event", _fake_create)

    import datetime as _dt

    fake = FakeClient()
    dispatch(fake, _msg("додай зустріч на завтра о 15:00 тест"))
    tomorrow = (_dt.date.today() + _dt.timedelta(days=1)).isoformat()
    assert "Подію створено" in fake.sent[-1]["text"]
    assert captured["start_local"] == f"{tomorrow}T15:00:00"
    assert captured["end_local"] == f"{tomorrow}T16:00:00"


def test_calendar_asks_for_time_when_missing(client, monkeypatch):
    monkeypatch.setattr(
        "app.core.config.settings.telegram_chat_id", "42", raising=False
    )
    _none_intent(monkeypatch)
    called = {"create": False}
    monkeypatch.setattr(
        "app.integrations.google.create_event",
        lambda db, **kw: called.__setitem__("create", True) or {},
    )
    fake = FakeClient()
    dispatch(fake, _msg("додай зустріч з Романом в календар roman@gmail.com"))
    assert "О котрій" in fake.sent[-1]["text"]
    assert called["create"] is False


def test_format_reminder_shows_range():
    from app.modules.automation.briefs import format_reminder

    start = dt.datetime(2026, 7, 9, 9, 0, tzinfo=dt.timezone.utc)
    end = dt.datetime(2026, 7, 9, 11, 0, tzinfo=dt.timezone.utc)
    txt = format_reminder({"summary": "Відкриття рахунків", "start": start, "end": end})
    assert "09:00–11:00" in txt
    assert "Відкриття рахунків" in txt
    assert "Через ~1 годину" in txt
