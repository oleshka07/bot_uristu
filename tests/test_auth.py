import base64


def test_auth_enforced_when_password_set(client, monkeypatch):
    from app import config

    monkeypatch.setattr(config.settings, "app_password", "secret123")
    monkeypatch.setattr(config.settings, "api_key", "svckey")

    # Protected without credentials.
    assert client.get("/api/dashboard").status_code == 401
    # Health stays open.
    assert client.get("/api/health").status_code == 200

    # Basic auth works.
    basic = "Basic " + base64.b64encode(b"admin:secret123").decode()
    assert client.get("/api/dashboard", headers={"Authorization": basic}).status_code == 200
    # Wrong password rejected.
    bad = "Basic " + base64.b64encode(b"admin:nope").decode()
    assert client.get("/api/dashboard", headers={"Authorization": bad}).status_code == 401

    # Service API key works for the bridge endpoint.
    assert client.get("/api/digest/text", headers={"X-API-Key": "svckey"}).status_code == 200
    assert client.get("/api/digest/text", headers={"X-API-Key": "wrong"}).status_code == 401


def test_no_auth_when_password_unset(client):
    # Default fixture leaves APP_PASSWORD empty → open.
    assert client.get("/api/dashboard").status_code == 200
