def test_health(client):
    assert client.get("/api/health").json()["status"] == "ok"


def test_contact_lifecycle_and_dashboard(client):
    r = client.post(
        "/api/contacts",
        json={
            "first_name": "Test",
            "last_name": "Person",
            "relationship_type": "friend",
            "contact_frequency": "weekly",
            "tags": ["vip"],
        },
    )
    assert r.status_code == 201
    cid = r.json()["id"]

    # Logging a positive interaction raises warmth.
    r = client.post(
        f"/api/contacts/{cid}/interactions",
        json={"channel": "call", "sentiment": 0.8, "summary": "Great chat"},
    )
    assert r.status_code == 201

    detail = client.get(f"/api/contacts/{cid}").json()
    assert detail["full_name"] == "Test Person"
    assert detail["warmth_score"] > 50
    assert detail["warmth_status"] in ("hot", "warm")
    assert "vip" in detail["tags"]

    dash = client.get("/api/dashboard").json()
    assert dash["stats"]["total_contacts"] == 1

    digest = client.get("/api/digest/text").json()
    assert digest["parse_mode"] == "HTML"
    assert "Networking" in digest["text"]


def test_search_and_delete(client):
    client.post("/api/contacts", json={"first_name": "Olena", "company": "SwipeScape"})
    client.post("/api/contacts", json={"first_name": "Marcus"})
    found = client.get("/api/contacts?search=swipe").json()
    assert len(found) == 1 and found[0]["first_name"] == "Olena"

    cid = found[0]["id"]
    assert client.delete(f"/api/contacts/{cid}").status_code == 204
    assert client.get(f"/api/contacts/{cid}").status_code == 404


def test_diagnostics(client):
    diag = client.get("/api/admin/diagnostics").json()
    assert "version" in diag
    assert "google" in diag["integrations"]
