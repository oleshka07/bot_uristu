"""Вечірнє зведення дня: ПК шле зріз, сервер о 22:10 звітує в Telegram."""

from datetime import date

import pytest

from app.modules.automation import telegram
from app.modules.insights import ai

SNAP = {
    "date": date.today().isoformat(),
    "active_min": 480,
    "on_task_min": 300,
    "off_task_min": 180,
    "apps": [{"name": "claude.exe", "min": 240}, {"name": "chrome.exe", "min": 150}],
    "windows": [{"title": "Демо PMS", "app": "chrome.exe", "min": 90}],
    "tasks": [{"title": "Підготувати демо PMS", "min": 200, "goal": "10 клієнтів"}],
    "goals": [{"title": "10 клієнтів", "min": 200}],
    "offtask_top": [{"title": "YouTube — огляди", "app": "chrome.exe", "min": 60}],
    "meetings_min": 30,
}


@pytest.fixture
def tg(monkeypatch):
    sent = []
    monkeypatch.setattr(telegram, "send_message", lambda text, **kw: sent.append(text) or True)
    monkeypatch.setattr(ai, "analyze_day", lambda digest, goals: None)  # без ШІ у тестах
    return sent


def _upload(client, payload=None):
    body = {"date": SNAP["date"], "payload": payload or SNAP}
    assert client.post("/api/timereport/daily", json=body).json() == {"ok": True}


def test_snapshot_upload_and_digest(client, tg):
    _upload(client)
    text = client.get("/api/timereport/daily/preview").json()["text"]

    assert "8г 00хв" in text                       # активний час
    assert "5г 00хв" in text and "(62%)" in text   # частка на задачах
    assert "10 клієнтів" in text                   # що вело до цілі
    assert "YouTube" in text                       # що не вело
    assert "claude" in text                        # вікна
    assert len(text) < 700, "зведення має бути коротким"


def test_second_upload_replaces_first(client, tg):
    """О 20:00 і о 22:00 — другий зріз оновлює перший, а не додає новий."""
    _upload(client, {**SNAP, "active_min": 100, "on_task_min": 10, "off_task_min": 90})
    _upload(client, SNAP)
    text = client.get("/api/timereport/daily/preview").json()["text"]
    assert "8г 00хв" in text and "1г 40хв" not in text


def test_digest_sent_to_telegram(client, tg):
    _upload(client)
    from app.core.database import SessionLocal
    from app.modules.timereport import service

    with SessionLocal() as db:
        assert service.send_daily(db) is True
    assert len(tg) == 1 and "День" in tg[0]


def test_no_snapshot_means_no_message(client, tg):
    """Компʼютер не вмикали — мовчимо, а не шлемо порожній звіт."""
    from app.core.database import SessionLocal
    from app.modules.timereport import service

    with SessionLocal() as db:
        assert service.send_daily(db) is False
    assert tg == []
