"""Contact-facts layer: creation, dedup, supersession, invalidation, history."""


def _new_contact(client) -> int:
    r = client.post("/api/contacts", json={"first_name": "Dana", "last_name": "Fact"})
    assert r.status_code == 201
    return r.json()["id"]


def test_add_fact_and_list_current(client):
    cid = _new_contact(client)
    r = client.post(
        f"/api/contacts/{cid}/facts",
        json={"fact_type": "interest", "value": "Trail running"},
    )
    assert r.status_code == 201
    fact = r.json()
    assert fact["value"] == "Trail running"
    assert fact["is_current"] is True

    facts = client.get(f"/api/contacts/{cid}/facts").json()
    assert [f["value"] for f in facts] == ["Trail running"]

    # It also surfaces on the contact detail read-model (current facts only).
    detail = client.get(f"/api/contacts/{cid}").json()
    assert any(f["value"] == "Trail running" for f in detail["facts"])


def test_duplicate_fact_is_idempotent(client):
    cid = _new_contact(client)
    a = client.post(
        f"/api/contacts/{cid}/facts",
        json={"fact_type": "interest", "value": "Chess"},
    ).json()
    # Same value (case-insensitive) → returns the existing fact, no duplicate.
    b = client.post(
        f"/api/contacts/{cid}/facts",
        json={"fact_type": "interest", "value": "chess"},
    ).json()
    assert a["id"] == b["id"]
    assert len(client.get(f"/api/contacts/{cid}/facts").json()) == 1


def test_single_valued_fact_supersedes_old(client):
    cid = _new_contact(client)
    old = client.post(
        f"/api/contacts/{cid}/facts",
        json={"fact_type": "employer", "value": "Works at Acme"},
    ).json()
    new = client.post(
        f"/api/contacts/{cid}/facts",
        json={"fact_type": "employer", "value": "Works at Globex"},
    ).json()

    current = client.get(f"/api/contacts/{cid}/facts").json()
    assert [f["value"] for f in current] == ["Works at Globex"]

    history = client.get(
        f"/api/contacts/{cid}/facts?include_history=true"
    ).json()
    values = {f["id"]: f for f in history}
    assert values[old["id"]]["is_current"] is False
    assert values[new["id"]]["is_current"] is True


def test_invalidate_fact(client):
    cid = _new_contact(client)
    fact = client.post(
        f"/api/contacts/{cid}/facts",
        json={"fact_type": "location", "value": "Lives in Kyiv"},
    ).json()
    r = client.post(f"/api/facts/{fact['id']}/invalidate")
    assert r.status_code == 200
    assert r.json()["is_current"] is False
    assert client.get(f"/api/contacts/{cid}/facts").json() == []
