"""'Later' shelf: capture links from chat, review them, close them off."""

from app.modules.telegram_bot.handlers import dispatch

from test_telegram_bot import FakeClient


def _msg(text: str, uid: int = 1) -> dict:
    return {"update_id": uid, "message": {"chat": {"id": 42}, "text": text}}


def _admin(monkeypatch):
    monkeypatch.setattr(
        "app.core.config.settings.telegram_chat_id", "42", raising=False
    )
    monkeypatch.setattr(
        "app.modules.insights.ai.parse_assistant_intent", lambda text, today: None
    )


def test_link_capture_classifies_and_lists(client, monkeypatch):
    _admin(monkeypatch)
    from app.core.database import SessionLocal
    from app.modules.resources import service as res
    from app.modules.resources.models import ResourceKind

    fake = FakeClient()
    dispatch(
        fake,
        _msg("https://www.youtube.com/watch?v=abc123 подивитись про воронки"),
    )
    assert "Відклав на потім" in fake.sent[-1]["text"]

    with SessionLocal() as db:
        items = res.list_open(db)
        assert len(items) == 1
        assert items[0].kind == ResourceKind.watch          # note + host agree
        assert "воронки" in (items[0].note or "")
        assert items[0].url.startswith("https://www.youtube.com")

    # Saving the same tab twice keeps one item.
    dispatch(fake, _msg("https://www.youtube.com/watch?v=abc123"))
    with SessionLocal() as db:
        assert len(res.list_open(db)) == 1

    dispatch(fake, _msg("/later"))
    listed = fake.sent[-1]
    assert "На потім" in listed["text"]
    assert "r:d:" in str(listed.get("reply_markup"))       # one-tap done buttons


def test_done_button_closes_item(client, monkeypatch):
    _admin(monkeypatch)
    from app.core.database import SessionLocal
    from app.modules.resources import service as res

    with SessionLocal() as db:
        r = res.create_resource(db, url="https://example.com/a", note="почитати")
        rid = r.id

    fake = FakeClient()
    dispatch(
        fake,
        {"update_id": 2, "callback_query": {"id": "cb", "data": f"r:d:{rid}",
         "message": {"chat": {"id": 42}, "message_id": 5}}},
    )
    with SessionLocal() as db:
        assert res.list_open(db) == []
        assert res.get_resource(db, rid).status.value == "done"


def test_reply_attaches_note_and_rekinds(client, monkeypatch):
    _admin(monkeypatch)
    from app.core.database import SessionLocal
    from app.modules.resources import service as res
    from app.modules.telegram_bot import handlers

    fake = FakeClient()
    dispatch(fake, _msg("https://example.com/deep-dive"))
    confirm_id = fake.sent[-1]["chat_id"] and 101
    # Map the confirmation message the way the handler does.
    with SessionLocal() as db:
        rid = res.list_open(db)[0].id
    handlers._resource_msgs[confirm_id] = rid

    dispatch(
        fake,
        {"update_id": 3, "message": {"chat": {"id": 42},
         "text": "це треба прочитати перед дзвінком",
         "reply_to_message": {"message_id": confirm_id}}},
    )
    with SessionLocal() as db:
        r = res.get_resource(db, rid)
        assert "прочитати" in (r.note or "")
        assert r.kind.value == "read"


def test_kind_and_title_helpers():
    from app.modules.resources import service as res

    assert res.guess_kind("https://youtu.be/x", None).value == "watch"
    assert res.guess_kind("https://example.com", "спробувати цей інструмент").value == "tool"
    assert res.guess_kind("https://github.com/a/b", None).value == "tool"
    assert res.title_from("https://example.com/some-post", None) == "example.com — some post"
    assert res.extract_urls("тут https://a.io/x і https://b.io") == [
        "https://a.io/x", "https://b.io",
    ]


def test_resources_api_roundtrip(client):
    r = client.post("/api/resources", json={"url": "https://api.example/x",
                                            "note": "подивитись"})
    assert r.status_code == 201
    rid = r.json()["id"]
    assert r.json()["kind"] == "watch"
    # idempotent on the same url
    again = client.post("/api/resources", json={"url": "https://api.example/x"})
    assert again.json()["id"] == rid
    assert client.get("/api/resources/stats").json()["open"] == 1
    client.patch(f"/api/resources/{rid}", json={"status": "done"})
    assert client.get("/api/resources").json() == []
