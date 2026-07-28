"""Підзадачі через синхронізацію + нагадування в Telegram (одне, без накопичення)."""

from datetime import datetime, timezone

import pytest

from app.modules.automation import telegram
from app.modules.tasks import service


@pytest.fixture
def tg(monkeypatch):
    """Підміна Telegram: памʼятає надіслане й видалене."""
    sent, deleted, counter = [], [], {"n": 100}

    def send_and_get_id(text, chat_id=None):
        counter["n"] += 1
        sent.append(text)
        return ("42", counter["n"])

    monkeypatch.setattr(telegram, "send_and_get_id", send_and_get_id)
    monkeypatch.setattr(telegram, "delete_message",
                        lambda chat, mid: deleted.append(mid) or True)
    return {"sent": sent, "deleted": deleted}


def _sync(client, tasks, **kw):
    body = {"tasks": tasks, "updated_at": datetime.now(timezone.utc).isoformat(), **kw}
    return client.post("/api/tasks/sync", json=body).json()


def test_subtask_survives_sync(client):
    """Головний баг: вкладеність губилась, бо сервер про неї не знав."""
    body = _sync(client, [
        {"uid": "aaa111", "title": "Продати будинок"},
        {"uid": "bbb222", "title": "Зробити фото", "parent_uid": "aaa111"},
    ])
    by_uid = {t["uid"]: t for t in body["tasks"]}
    assert by_uid["bbb222"]["parent_id"] == by_uid["aaa111"]["id"]
    assert by_uid["aaa111"]["parent_id"] is None

    # Повторна синхронізація не втрачає звʼязок.
    body = _sync(client, [
        {"uid": "aaa111", "title": "Продати будинок"},
        {"uid": "bbb222", "title": "Зробити фото", "parent_uid": "aaa111"},
    ])
    by_uid = {t["uid"]: t for t in body["tasks"]}
    assert by_uid["bbb222"]["parent_id"] == by_uid["aaa111"]["id"]

    # Підзадачу можна відчепити.
    body = _sync(client, [
        {"uid": "aaa111", "title": "Продати будинок"},
        {"uid": "bbb222", "title": "Зробити фото"},
    ])
    assert {t["uid"]: t for t in body["tasks"]}["bbb222"]["parent_id"] is None


def test_parent_created_in_same_request(client):
    """Батько й дитина приїхали разом, обидва нові — звʼязок має зʼявитись."""
    body = _sync(client, [
        {"uid": "p1", "title": "Батько"},
        {"uid": "c1", "title": "Дитина", "parent_uid": "p1"},
    ])
    by_uid = {t["uid"]: t for t in body["tasks"]}
    assert by_uid["c1"]["parent_id"] == by_uid["p1"]["id"]


def test_nudge_replaces_previous_message(client, tg):
    client.post("/api/tasks", json={"title": "Демо PMS", "status": "current"})
    client.post("/api/tasks", json={"title": "Ціни Йоргу", "duration_min": 5})

    assert client.post("/api/tasks/nudge").json() == {"sent": True}
    assert tg["deleted"] == []                    # першого разу видаляти нічого
    assert "Демо PMS" in tg["sent"][0] and "Ціни Йоргу" in tg["sent"][0]

    assert client.post("/api/tasks/nudge").json() == {"sent": True}
    assert tg["deleted"] == [101], tg            # друге прибрало перше
    assert len(tg["sent"]) == 2

    client.post("/api/tasks/nudge")
    assert tg["deleted"] == [101, 102], tg       # і так щоразу — в чаті один меседж


def test_nudge_says_when_no_task_taken(client, tg):
    client.post("/api/tasks", json={"title": "Нічия задача"})
    client.post("/api/tasks/nudge")
    assert "Задачу не взято" in tg["sent"][0]


def test_nudge_silent_when_nothing_to_do(client, tg):
    assert client.post("/api/tasks/nudge").json() == {"sent": False}
    assert tg["sent"] == []
