"""Монітор соцмереж: нові дописи -> факти в досьє + приводи написати."""

from datetime import datetime, timedelta, timezone

import pytest

from app.core.database import SessionLocal
from app.modules.contacts.models import Contact
from app.modules.insights.models import ContactFact, FactType, LifeEvent
from app.modules.integrations.social import monitor, posts as providers
from app.modules.integrations.social.models import SocialPost


def _post(pid, caption, days_ago=1, **kw) -> providers.PostData:
    return providers.PostData(
        external_id=pid,
        url=f"https://www.instagram.com/p/{pid}/",
        caption=caption,
        alt_text=kw.get("alt_text"),
        media_type=kw.get("media_type", "image"),
        posted_at=datetime.now(timezone.utc) - timedelta(days=days_ago),
    )


def _contact(name="Олена", ig="https://www.instagram.com/olena.k/", **kw) -> int:
    with SessionLocal() as db:
        c = Contact(first_name=name, instagram_url=ig, **kw)
        db.add(c)
        db.commit()
        return c.id


@pytest.fixture
def feed(monkeypatch):
    """Підмінює провайдера: віддає задані дописи, рахує звернення."""
    state = {"posts": [], "calls": 0, "configured": True}

    def fake(profile_url):
        state["calls"] += 1
        return list(state["posts"])

    monkeypatch.setattr(providers, "fetch_posts", lambda platform, url: fake(url))
    monkeypatch.setattr(providers, "configured", lambda platform="instagram": state["configured"])
    return state


@pytest.fixture
def ai(monkeypatch):
    from app.modules.insights import ai as ai_module

    state = {
        "digest": {
            "facts": [{"fact_type": "employer", "value": "Очолила маркетинг у Nova", "confidence": "high", "post_id": "p1"}],
            "hooks": [{"event_type": "new_job", "title": "Нова посада в Nova", "description": "Написала про перший день", "post_id": "p1"}],
        },
        "seen": [],
    }

    def digest(contact, posts):
        state["seen"].append([p["external_id"] for p in posts])
        return state["digest"]

    monkeypatch.setattr(ai_module, "digest_social_posts", digest)
    return state


# ── розбір відповіді провайдера ──────────────────────────────────────────────


def test_handle_is_read_from_profile_urls():
    assert providers.instagram_handle("https://www.instagram.com/olena.k/") == "olena.k"
    assert providers.instagram_handle("instagram.com/@olena.k") == "olena.k"
    assert providers.instagram_handle("https://www.instagram.com/p/abc123/") is None
    assert providers.instagram_handle(None) is None


def test_apify_items_are_parsed_tolerantly():
    items = [
        {"id": "1", "caption": "Перший день у Nova", "timestamp": "2026-09-01T10:00:00.000Z", "type": "Image", "url": "u1"},
        {"shortCode": "2", "text": "reel", "takenAt": 1756800000, "productType": "clips"},
        {"caption": "без id — пропускаємо"},
        "сміття",
    ]
    parsed = providers.parse_apify_items(items)
    assert [p.external_id for p in parsed] == ["1", "2"]
    assert parsed[0].posted_at.year == 2026 and parsed[0].media_type == "image"
    assert parsed[1].media_type == "video" and parsed[1].posted_at is not None


def test_without_a_token_the_provider_is_silent(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "apify_api_token", None)
    assert providers.fetch_instagram_posts_apify("https://www.instagram.com/x/") == []


# ── збереження і дедуп ───────────────────────────────────────────────────────


def test_only_unseen_posts_are_stored(client, feed, ai):
    cid = _contact()
    feed["posts"] = [_post("p1", "Перший день у Nova"), _post("p2", "Кава")]
    with SessionLocal() as db:
        c = db.get(Contact, cid)
        first = monitor.check_contact(db, c)
        assert first["new"] == 2

        feed["posts"].append(_post("p3", "Виступ на конференції"))
        second = monitor.check_contact(db, c)
        assert second["new"] == 1                      # p1, p2 уже відомі
        assert db.query(SocialPost).count() == 3
        assert ai["seen"] == [["p1", "p2"], ["p3"]]      # моделі йде лише нове


def test_facts_land_in_the_dossier_with_provenance(client, feed, ai):
    cid = _contact()
    feed["posts"] = [_post("p1", "Перший день у Nova")]
    with SessionLocal() as db:
        monitor.check_contact(db, db.get(Contact, cid))
        fact = db.query(ContactFact).one()
        assert fact.fact_type == FactType.employer
        assert fact.value == "Очолила маркетинг у Nova"
        assert fact.source == "instagram"
        assert fact.source_ref == "post:p1"             # звідки взялося — видно


def test_hooks_become_life_events_the_queue_can_use(client, feed, ai):
    cid = _contact()
    feed["posts"] = [_post("p1", "Перший день у Nova", days_ago=2)]
    with SessionLocal() as db:
        monitor.check_contact(db, db.get(Contact, cid))
        ev = db.query(LifeEvent).one()
        assert ev.event_type == "new_job"
        assert ev.title == "Нова посада в Nova"
        assert ev.source == "instagram"
        assert ev.event_date == (datetime.now(timezone.utc) - timedelta(days=2)).date()


def test_same_hook_is_not_added_twice(client, feed, ai):
    cid = _contact()
    feed["posts"] = [_post("p1", "Перший день у Nova")]
    with SessionLocal() as db:
        c = db.get(Contact, cid)
        monitor.check_contact(db, c)
        feed["posts"].append(_post("p2", "Ще про роботу"))
        ai["digest"]["hooks"][0]["post_id"] = "p2"
        monitor.check_contact(db, c)
        assert db.query(LifeEvent).count() == 1


def test_posts_are_marked_processed_and_contact_checked(client, feed, ai):
    cid = _contact()
    feed["posts"] = [_post("p1", "x")]
    with SessionLocal() as db:
        c = db.get(Contact, cid)
        assert c.social_checked_at is None
        monitor.check_contact(db, c)
        assert c.social_checked_at is not None
        assert db.query(SocialPost).one().processed_at is not None


def test_nothing_new_still_marks_the_contact_checked(client, feed, ai):
    cid = _contact()
    with SessionLocal() as db:
        c = db.get(Contact, cid)
        r = monitor.check_contact(db, c)
        assert r == {"fetched": 0, "new": 0, "facts": 0, "hooks": 0}
        assert c.social_checked_at is not None


# ── хто в черзі ──────────────────────────────────────────────────────────────


def test_candidates_need_instagram_and_not_stoplist(client):
    _contact("З інстою")
    _contact("Без", ig=None)
    _contact("Стоп", do_not_contact=True)
    with SessionLocal() as db:
        assert [c.first_name for c in monitor.candidates(db)] == ["З інстою"]


def test_recently_checked_contacts_wait_their_turn(client, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "social_monitor_every_days", 3)
    now = datetime.now(timezone.utc)
    _contact("Щойно", social_checked_at=now - timedelta(hours=5))
    _contact("Давно", social_checked_at=now - timedelta(days=10))
    _contact("Ніколи")
    with SessionLocal() as db:
        names = [c.first_name for c in monitor.candidates(db)]
    assert names == ["Ніколи", "Давно"]          # найдавніше перевірені — першими


def test_run_is_capped_and_a_failure_does_not_stop_the_sweep(client, feed, ai, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "social_monitor_per_run", 2)
    _contact("Перша")
    _contact("Друга")
    _contact("Третя")
    feed["posts"] = [_post("p1", "x")]

    original = monitor.check_contact

    def flaky(db, contact):
        if contact.first_name == "Перша":
            raise RuntimeError("провайдер впав")
        return original(db, contact)

    monkeypatch.setattr(monitor, "check_contact", flaky)
    report = monitor.run_monitor()
    assert report["failed"] == 1
    assert report["checked"] == 1                  # ліміт 2: одна впала, одна пройшла
    assert report["skipped"] is None


def test_unconfigured_provider_skips_quietly(client, feed):
    feed["configured"] = False
    _contact()
    report = monitor.run_monitor()
    assert report["skipped"] == "provider not configured"
    assert report["checked"] == 0


# ── дописи в промпті ─────────────────────────────────────────────────────────


def test_recent_posts_reach_the_prompt_context(client, feed, ai):
    from app.modules.insights.ai import _contact_context

    cid = _contact()
    feed["posts"] = [_post("p1", "Перший день у Nova")]
    with SessionLocal() as db:
        c = db.get(Contact, cid)
        monitor.check_contact(db, c)
        text = _contact_context(c)
    assert "Recent social posts" in text
    assert "Перший день у Nova" in text


# ── API ──────────────────────────────────────────────────────────────────────


def test_api_status_check_and_posts(client, feed, ai):
    cid = _contact()
    feed["posts"] = [_post("p1", "Перший день у Nova")]

    status = client.get("/api/social/status").json()
    assert status["configured"] is True and status["candidates"] == 1

    r = client.post(f"/api/social/contacts/{cid}/check").json()
    assert r["new"] == 1 and r["facts"] == 1 and r["hooks"] == 1

    posts = client.get(f"/api/social/contacts/{cid}/posts").json()
    assert [p["external_id"] for p in posts] == ["p1"]

    no_ig = _contact("Без", ig=None)
    assert client.post(f"/api/social/contacts/{no_ig}/check").status_code == 400
