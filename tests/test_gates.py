"""Ворота: задачі поза кодом, які агент помічає в сесії розробки."""

from datetime import datetime, timedelta, timezone

from app.core.database import SessionLocal
from app.modules.gates import service as gates
from app.modules.tasks.models import Task, TaskStatus


def _age(uid: str, hours: float) -> None:
    with SessionLocal() as db:
        task = db.query(Task).filter(Task.uid == uid).one()
        task.created_at = datetime.now(timezone.utc) - timedelta(hours=hours)
        db.commit()


def test_gate_links_to_a_goal_by_part_of_its_title(client):
    client.post("/api/goals", json={"title": "Підключення клієнтів", "priority": 100})
    gate = client.post(
        "/api/gates", json={"text": "зробити скринкаст", "goal": "підключення"}
    ).json()
    assert gate["goal"] == "Підключення клієнтів"
    assert gate["uid"] and gate["age_hours"] == 0


def test_gate_without_a_matching_goal_is_still_created(client):
    gate = client.post(
        "/api/gates", json={"text": "підписати договір", "goal": "чогось такого немає"}
    ).json()
    assert gate["goal"] is None


def test_open_gates_are_listed_oldest_first(client):
    first = client.post("/api/gates", json={"text": "старі"}).json()
    client.post("/api/gates", json={"text": "нові"})
    _age(first["uid"], 50)

    listed = client.get("/api/gates").json()
    assert [g["text"] for g in listed] == ["старі", "нові"]
    assert listed[0]["age_hours"] >= 50


def test_closing_a_gate_removes_it_from_the_list(client):
    gate = client.post("/api/gates", json={"text": "подзвонити в банк"}).json()
    assert client.post(f"/api/gates/{gate['uid']}/done").json()["uid"] == gate["uid"]
    assert client.get("/api/gates").json() == []
    assert client.post("/api/gates/nosuch/done").status_code == 404


def test_gates_are_ordinary_tasks(client):
    """Один список задач замість двох — ворота видно і в /api/tasks."""
    client.post("/api/gates", json={"text": "записати відео"})
    titles = [t["title"] for t in client.get("/api/tasks").json()]
    assert "записати відео" in titles


def test_only_gates_older_than_a_day_are_stale(client):
    fresh = client.post("/api/gates", json={"text": "свіжі"}).json()
    old = client.post("/api/gates", json={"text": "застояні"}).json()
    _age(old["uid"], 30)

    with SessionLocal() as db:
        stale = gates.stale_gates(db)
        assert [t.title for t in stale] == ["застояні"]
        assert fresh["uid"] not in [t.uid for t in stale]


def test_nudge_stays_silent_when_nothing_is_stale(client):
    client.post("/api/gates", json={"text": "свіжі"})
    assert client.post("/api/gates/nudge").json() == {"sent": False, "text": None}


def test_nudge_fires_once_then_holds_its_tongue(client):
    client.post("/api/goals", json={"title": "Підключення клієнтів", "priority": 100})
    gate = client.post(
        "/api/gates", json={"text": "скринкаст", "goal": "підключення"}
    ).json()
    _age(gate["uid"], 30)

    first = client.post("/api/gates/nudge").json()
    assert first["sent"] is True
    assert "скринкаст" in first["text"]
    assert "Блокує: Підключення клієнтів" in first["text"]

    # Другий пінг поспіль — це фон, який перестають помічати.
    assert client.post("/api/gates/nudge").json()["sent"] is False


def test_weekly_summary_surfaces_stale_gates(client, monkeypatch):
    from app.modules.coach import jobs
    from app.modules.insights import ai

    monkeypatch.setattr(ai, "coach_week_verdict", lambda *a, **kw: None)
    gate = client.post("/api/gates", json={"text": "надіслати рахунок"}).json()
    _age(gate["uid"], 40)

    with SessionLocal() as db:
        text = jobs.weekly_text(db)
    assert "надіслати рахунок" in text
    assert "висять понад добу" in text


def test_done_gate_is_neither_open_nor_stale(client):
    gate = client.post("/api/gates", json={"text": "закрите"}).json()
    _age(gate["uid"], 40)
    client.post(f"/api/gates/{gate['uid']}/done")

    with SessionLocal() as db:
        assert gates.open_gates(db) == []
        assert gates.stale_gates(db) == []
        task = db.query(Task).filter(Task.uid == gate["uid"]).one()
        assert task.status == TaskStatus.done
