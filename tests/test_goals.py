"""Goals: CRUD, contact linking, importance boost, queue priority."""


def _mk_goal(client, title="Launch", **kw):
    r = client.post("/api/goals", json={"title": title, **kw})
    assert r.status_code == 201
    return r.json()


def test_goal_crud_and_linking(client):
    r = client.post("/api/contacts", json={"first_name": "Investor", "last_name": "One"})
    cid = r.json()["id"]
    goal = _mk_goal(client, "Raise round", priority=90)

    linked = client.post(f"/api/goals/{goal['id']}/contacts/{cid}").json()
    assert [c["id"] for c in linked["contacts"]] == [cid]

    # Goal shows up on the contact detail.
    detail = client.get(f"/api/contacts/{cid}").json()
    assert any(g["title"] == "Raise round" for g in detail["goals"])

    # Unlink.
    after = client.delete(f"/api/goals/{goal['id']}/contacts/{cid}").json()
    assert after["contacts"] == []


def test_active_goal_boosts_importance_and_queue(client, monkeypatch):
    from datetime import datetime, timedelta, timezone
    from app.core.database import SessionLocal
    from app.modules.telegram_bot import service as svc

    # Two due, reachable contacts; the shallow one gets tied to an active goal.
    with SessionLocal() as db:
        from app.modules.contacts.models import Contact, Frequency
        from app.modules.interactions.models import Channel, Direction, Interaction
        from app import warmth

        def due(name, cid, days, msgs=1):
            c = Contact(first_name=name, contact_frequency=Frequency.monthly, telegram_chat_id=cid)
            db.add(c); db.flush()
            for i in range(msgs):
                db.add(Interaction(contact_id=c.id,
                    occurred_at=datetime.now(timezone.utc) - timedelta(days=days + i),
                    channel=Channel.message, direction=Direction.outbound,
                    summary="x", source="telegram"))
            db.flush(); db.refresh(c); warmth.refresh(c); db.commit()
            return c.id

        deep = due("Deep", 601, 60, msgs=30)     # importance 3 by history
        shallow = due("Shallow", 602, 300, msgs=1)  # importance 1 normally
        svc.upsert_connection(db, "bc", 42, True)

    # Without a goal, the deep-history contact would win on a tie of importance.
    # Link the shallow one to an active goal → importance jumps to 3, and it is
    # far more overdue, so it should now lead the queue.
    goal = _mk_goal(client, "Ship v2")
    client.post(f"/api/goals/{goal['id']}/contacts/{shallow}")

    with SessionLocal() as db:
        from app.modules.contacts.models import Contact
        c = db.get(Contact, shallow)
        assert svc.effective_importance(c) == 3
        contact, _ = svc.next_outreach_contact(db)
        assert contact.first_name == "Shallow"
