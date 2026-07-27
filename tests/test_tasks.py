"""Tasks: Dividify-style ordering + sync with the PC agent."""

from datetime import date, datetime, timedelta, timezone


def _mk(client, title, **kw):
    r = client.post("/api/tasks", json={"title": title, **kw})
    assert r.status_code == 201, r.text
    return r.json()


def test_order_status_then_date_then_duration(client):
    today = date.today().isoformat()
    later = (date.today() + timedelta(days=5)).isoformat()

    _mk(client, "Звіт", duration_min=180, due_date=today)
    _mk(client, "Дзвінок", duration_min=5, due_date=today)
    _mk(client, "Лист", duration_min=8, due_date=today)
    _mk(client, "Пізніше", duration_min=5, due_date=later)
    _mk(client, "Чекаю відповідь", status="hold", duration_min=1, due_date=today)
    _mk(client, "ЗАРАЗ", status="immediate", duration_min=240, due_date=later)

    titles = [t["title"] for t in client.get("/api/tasks").json()]
    # immediate завжди перша, попри 4 години і далеку дату
    assert titles[0] == "ЗАРАЗ"
    # серед сьогоднішніх — спочатку короткі (швидкі перемоги)
    assert titles[1:4] == ["Дзвінок", "Лист", "Звіт"]
    # пізніша дата — після сьогоднішніх; hold — в самому кінці
    assert titles.index("Пізніше") < titles.index("Чекаю відповідь")
    assert titles[-1] == "Чекаю відповідь"

    assert client.get("/api/tasks/next").json()["title"] == "ЗАРАЗ"


def test_urgent_rises_on_due_day(client):
    _mk(client, "Звичайна", due_date=date.today().isoformat(), duration_min=5)
    _mk(client, "Дедлайн сьогодні", status="urgent",
        due_date=date.today().isoformat(), duration_min=200)
    assert client.get("/api/tasks").json()[0]["title"] == "Дедлайн сьогодні"

    # Статус важить найбільше: urgent вище звичайних навіть із дальшою датою,
    # а в день дедлайну підіймається ще вище (майже нарівні з immediate).
    _mk(client, "Дедлайн потім", status="urgent",
        due_date=(date.today() + timedelta(days=3)).isoformat(), duration_min=200)
    titles = [t["title"] for t in client.get("/api/tasks").json()]
    assert titles[0] == "Дедлайн сьогодні"
    assert titles.index("Дедлайн потім") < titles.index("Звичайна")


def test_done_hidden_unless_asked(client):
    t = _mk(client, "Зроблю")
    client.patch(f"/api/tasks/{t['id']}", json={"status": "done"})
    assert client.get("/api/tasks").json() == []
    assert len(client.get("/api/tasks?include_done=true").json()) == 1


def test_sync_creates_updates_and_respects_newer_server(client):
    # 1. ПК шле дві нові задачі — сервер видає їм uid
    r = client.post("/api/tasks/sync", json={
        "tasks": [{"title": "З ПК А"}, {"title": "З ПК Б", "status": "hold"}],
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })
    body = r.json()
    assert body["applied"] == 2
    uids = {t["title"]: t["uid"] for t in body["tasks"]}
    assert all(uids.values())

    # 2. Правка на сервері новіша за файл на ПК → перемагає сервер
    server_task = next(t for t in body["tasks"] if t["title"] == "З ПК А")
    client.patch(f"/api/tasks/{server_task['id']}", json={"title": "Перейменовано у вебі"})
    stale = datetime.now(timezone.utc) - timedelta(hours=1)
    r = client.post("/api/tasks/sync", json={
        "tasks": [{"uid": uids["З ПК А"], "title": "Стара назва з ПК"}],
        "updated_at": stale.isoformat(),
    })
    titles = [t["title"] for t in r.json()["tasks"]]
    assert "Перейменовано у вебі" in titles and "Стара назва з ПК" not in titles

    # 3. Свіжа правка на ПК — перемагає ПК
    r = client.post("/api/tasks/sync", json={
        "tasks": [{"uid": uids["З ПК А"], "title": "Нова назва з ПК"}],
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })
    assert "Нова назва з ПК" in [t["title"] for t in r.json()["tasks"]]


def test_authoritative_sync_deletes_missing(client):
    now = datetime.now(timezone.utc).isoformat()
    body = client.post("/api/tasks/sync", json={
        "tasks": [{"title": "Лишиться"}, {"title": "Зникне"}], "updated_at": now,
    }).json()
    uid_keep = next(t["uid"] for t in body["tasks"] if t["title"] == "Лишиться")

    # Без authoritative відсутні задачі НЕ видаляються (звичайне підтягування).
    r = client.post("/api/tasks/sync", json={
        "tasks": [{"uid": uid_keep, "title": "Лишиться"}], "updated_at": now,
    }).json()
    assert r["deleted"] == 0 and len(r["tasks"]) == 2

    # З authoritative — файл на ПК є істиною: рядок прибрали → задача видалена.
    r = client.post("/api/tasks/sync", json={
        "tasks": [{"uid": uid_keep, "title": "Лишиться"}],
        "updated_at": now, "authoritative": True,
    }).json()
    assert r["deleted"] == 1
    assert [t["title"] for t in client.get("/api/tasks").json()] == ["Лишиться"]
