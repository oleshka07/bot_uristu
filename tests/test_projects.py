"""Ієрархія: проєкт → ціль → задача. Проєкти нормалізовані в таблицю."""


def test_project_created_from_task_name(client):
    """focus.md знає лише назву — сервер сам заводить рядок у projects."""
    t = client.post("/api/tasks", json={"title": "Демо", "project": "PMS"}).json()
    assert t["project"] == "PMS" and t["project_id"], t

    projects = client.get("/api/projects").json()
    assert [p["name"] for p in projects] == ["PMS"]

    # Друга задача з тим самим проєктом — той самий рядок, не дубль.
    t2 = client.post("/api/tasks", json={"title": "Ще одна", "project": "PMS"}).json()
    assert t2["project_id"] == t["project_id"]
    assert len(client.get("/api/projects").json()) == 1


def test_project_delete_keeps_tasks(client):
    client.post("/api/tasks", json={"title": "Демо", "project": "КЕМП"})
    pid = client.get("/api/projects").json()[0]["id"]
    client.delete(f"/api/projects/{pid}")

    tasks = client.get("/api/tasks").json()
    assert [t["title"] for t in tasks] == ["Демо"]     # задача жива
    assert tasks[0]["project"] is None                 # просто без проєкту
    assert client.get("/api/projects").json() == []


def test_project_rename(client):
    p = client.post("/api/projects", json={"name": "Стара"}).json()
    out = client.patch(f"/api/projects/{p['id']}", json={"name": "Нова"}).json()
    assert out["name"] == "Нова"


def test_duties_are_not_in_the_task_queue(client):
    client.post("/api/tasks", json={"title": "Звичайна"})
    client.post("/api/tasks", json={"title": "Бухзвітність", "kind": "duty",
                                    "item_type": "файл", "counterpart": "Податкова",
                                    "recur": "monthly"})
    client.post("/api/tasks", json={"title": "Оплата від клієнта", "kind": "expectation",
                                    "counterpart": "Клієнт"})

    assert [t["title"] for t in client.get("/api/tasks").json()] == ["Звичайна"]

    duties = client.get("/api/tasks?kind=duty").json()
    assert [t["title"] for t in duties] == ["Бухзвітність"]
    assert duties[0]["item_type"] == "файл" and duties[0]["recur"] == "monthly"
    assert duties[0]["counterpart"] == "Податкова"

    waits = client.get("/api/tasks?kind=expectation").json()
    assert [t["title"] for t in waits] == ["Оплата від клієнта"]


def test_sync_carries_kind_and_project(client):
    from datetime import datetime, timezone

    body = client.post("/api/tasks/sync", json={
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "tasks": [
            {"uid": "t1", "title": "Задача", "project": "PMS"},
            {"uid": "d1", "title": "Звітність", "kind": "duty", "project": "PMS",
             "item_type": "файл", "counterpart": "Податкова", "recur": "monthly"},
        ],
    }).json()

    by_uid = {t["uid"]: t for t in body["tasks"]}
    assert by_uid["d1"]["kind"] == "duty"
    assert by_uid["d1"]["counterpart"] == "Податкова"
    # Обидва в одному проєкті — і це один рядок у projects.
    assert by_uid["t1"]["project_id"] == by_uid["d1"]["project_id"]
    assert [p["name"] for p in client.get("/api/projects").json()] == ["PMS"]
    # У черзі задач обовʼязку немає.
    assert [t["title"] for t in client.get("/api/tasks").json()] == ["Задача"]


def test_goal_links_to_project(client):
    p = client.post("/api/projects", json={"name": "PMS"}).json()
    g = client.post("/api/goals", json={"title": "10 клієнтів",
                                        "project_id": p["id"]}).json()
    assert g["project_id"] == p["id"]
