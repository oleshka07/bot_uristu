"""Ideas capture: free-form dump, grow, list — via text and voice."""

from app.modules.telegram_bot.handlers import dispatch

from test_telegram_bot import FakeClient


def _msg(text: str, uid: int = 1) -> dict:
    return {"update_id": uid, "message": {"chat": {"id": 42}, "text": text}}


def _admin(monkeypatch):
    monkeypatch.setattr(
        "app.core.config.settings.telegram_chat_id", "42", raising=False
    )


def _ai_none(monkeypatch):
    # No AI in tests → classifier returns None; keyword nets must carry it.
    monkeypatch.setattr(
        "app.modules.insights.ai.parse_assistant_intent", lambda text, today: None
    )


def test_idea_capture_and_grow(client, monkeypatch):
    _admin(monkeypatch)
    _ai_none(monkeypatch)
    from app.core.database import SessionLocal
    from app.modules.ideas import service as ideas

    long_body = "Є ідея зробити маркетплейс для tiny house. " + ("деталь " * 400)
    fake = FakeClient()
    dispatch(fake, _msg(long_body))
    assert "Записав ідею" in fake.sent[-1]["text"]

    with SessionLocal() as db:
        items = ideas.list_ideas(db)
        assert len(items) == 1
        assert len(items[0].body) > 2000          # long dumps preserved
        assert items[0].title.startswith("зробити маркетплейс")  # lead stripped
        first_len = len(items[0].body)
        first_id = items[0].id

    # Grow the same idea.
    dispatch(fake, _msg("продовж ідею: ще можна додати підписку на обслуговування"))
    assert "Доповнив ідею" in fake.sent[-1]["text"]
    with SessionLocal() as db:
        items = ideas.list_ideas(db)
        assert len(items) == 1 and items[0].id == first_id
        assert len(items[0].body) > first_len
        assert "підписку на обслуговування" in items[0].body


def test_ideas_list_and_open_commands(client, monkeypatch):
    _admin(monkeypatch)
    _ai_none(monkeypatch)
    from app.core.database import SessionLocal
    from app.modules.ideas import service as ideas

    with SessionLocal() as db:
        idea = ideas.create_idea(db, "Ідея про CRM для ріелторів")
        iid = idea.id

    fake = FakeClient()
    dispatch(fake, _msg("/ideas"))
    assert "CRM для ріелторів" in fake.sent[-1]["text"]

    dispatch(fake, _msg(f"/idea {iid}"))
    assert "CRM для ріелторів" in fake.sent[-1]["text"]


def test_voice_idea_routes_to_ideas_not_intake(client, monkeypatch):
    _admin(monkeypatch)
    _ai_none(monkeypatch)
    from app.core.database import SessionLocal
    from app.modules.ideas import service as ideas

    monkeypatch.setattr(
        "app.modules.telegram_bot.handlers.transcribe_ogg",
        lambda audio: "є ідея запустити подкаст про нерухомість у Чехії",
    )
    fake = FakeClient()
    monkeypatch.setattr(fake, "download_file", lambda fid: b"audio")
    dispatch(
        fake,
        {"update_id": 1, "message": {"chat": {"id": 42},
         "voice": {"file_id": "f"}}},
    )
    assert "Записав ідею" in fake.sent[-1]["text"]
    with SessionLocal() as db:
        assert len(ideas.list_ideas(db)) == 1


def test_idea_api_roundtrip(client):
    r = client.post("/api/ideas", json={"body": "API idea body"})
    assert r.status_code == 201
    iid = r.json()["id"]
    r2 = client.post(f"/api/ideas/{iid}/append", json={"text": "more"})
    assert "more" in r2.json()["body"]
    assert client.get("/api/ideas").json()  # non-empty
