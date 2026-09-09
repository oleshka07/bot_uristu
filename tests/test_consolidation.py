"""Памʼять про людей: досьє потрапляє в промпт, консолідація йде сама."""

from datetime import datetime, timedelta, timezone

import pytest

from app.core.database import SessionLocal
from app.modules.contacts.models import Contact
from app.modules.insights import service as insights
from app.modules.insights.models import ContactFact, FactType
from app.modules.interactions.models import Channel, Direction, Interaction


def _contact(name="Марія", interactions=0, **kw) -> int:
    with SessionLocal() as db:
        contact = Contact(first_name=name, **kw)
        db.add(contact)
        db.flush()
        for i in range(interactions):
            db.add(
                Interaction(
                    contact_id=contact.id,
                    occurred_at=datetime.now(timezone.utc) - timedelta(days=i),
                    channel=Channel.message,
                    direction=Direction.inbound,
                    summary=f"повідомлення {i}",
                )
            )
        db.commit()
        return contact.id


@pytest.fixture
def ai(monkeypatch):
    """Керована модель: досьє і факти, які вона «витягує»."""
    from app.modules.insights import ai as ai_module

    state = {
        "enabled": True,
        "dossier": "Марія — CTO в Acme, цікавиться бігом.",
        "facts": [
            {"fact_type": "employer", "value": "Працює в Acme", "confidence": "high"},
            {"fact_type": "interest", "value": "Бігає трейли", "confidence": "medium"},
        ],
        "calls": 0,
    }

    def generate_dossier(contact):
        state["calls"] += 1
        return state["dossier"]

    monkeypatch.setattr(ai_module.llm, "enabled", lambda: state["enabled"])
    monkeypatch.setattr(ai_module, "generate_dossier", generate_dossier)
    monkeypatch.setattr(ai_module, "extract_facts", lambda contact: state["facts"])
    return state


# ── 1. Досьє в промпті ──────────────────────────────────────────────────────


def test_dossier_is_the_first_thing_the_model_sees(client):
    from app.modules.insights.ai import _contact_context

    cid = _contact(ai_dossier="Давній партнер, познайомились на конференції.")
    with SessionLocal() as db:
        text = _contact_context(db.get(Contact, cid))

    assert text.startswith("Dossier (consolidated memory):")
    assert "познайомились на конференції" in text
    # Решта контексту нікуди не поділася.
    assert "Name: Марія" in text


def test_without_a_dossier_the_context_is_unchanged(client):
    from app.modules.insights.ai import _contact_context

    cid = _contact()
    with SessionLocal() as db:
        text = _contact_context(db.get(Contact, cid))
    assert "Dossier" not in text
    assert text.startswith("Name: Марія")


# ── 2. Консолідація ─────────────────────────────────────────────────────────


def test_consolidation_writes_dossier_facts_and_the_counter(client, ai):
    cid = _contact(interactions=3)
    with SessionLocal() as db:
        contact = db.get(Contact, cid)
        result = insights.consolidate_contact(db, contact)

        assert result == {"dossier": True, "facts": 2}
        assert contact.ai_dossier == "Марія — CTO в Acme, цікавиться бігом."
        assert contact.ai_dossier_updated_at is not None
        assert contact.consolidated_count == 3
        values = {f.value for f in db.query(ContactFact).all()}
        assert values == {"Працює в Acme", "Бігає трейли"}


def test_rerun_does_not_duplicate_facts(client, ai):
    cid = _contact(interactions=1)
    with SessionLocal() as db:
        contact = db.get(Contact, cid)
        insights.consolidate_contact(db, contact)
        insights.consolidate_contact(db, contact)
        assert db.query(ContactFact).count() == 2


def test_new_employer_supersedes_the_old_one_instead_of_stacking(client, ai):
    cid = _contact(interactions=1)
    with SessionLocal() as db:
        contact = db.get(Contact, cid)
        insights.consolidate_contact(db, contact)
        ai["facts"] = [{"fact_type": "employer", "value": "Перейшла в Globex", "confidence": "high"}]
        insights.consolidate_contact(db, contact)

        employers = db.query(ContactFact).filter(ContactFact.fact_type == FactType.employer).all()
        current = [f.value for f in employers if f.is_current]
        gone = [f.value for f in employers if not f.is_current]
        assert current == ["Перейшла в Globex"]
        assert gone == ["Працює в Acme"]      # історія лишилась, не стерта


def test_without_ai_nothing_is_touched(client, ai):
    ai["enabled"] = False
    cid = _contact(interactions=6)
    with SessionLocal() as db:
        contact = db.get(Contact, cid)
        assert insights.consolidate_contact(db, contact) == {"skipped": "ai unavailable"}
        assert contact.ai_dossier is None
        # Лічильник не рухається — інакше контакт вважався б консолідованим.
        assert contact.consolidated_count == 0


def test_due_when_enough_new_interactions_piled_up(client, ai):
    fresh = _contact("Багато", interactions=5)
    quiet = _contact("Мало", interactions=2, ai_dossier_updated_at=datetime.now(timezone.utc))
    with SessionLocal() as db:
        due = [c.first_name for c in insights.due_for_consolidation(db)]
    assert "Багато" in due
    assert "Мало" not in due
    assert quiet and fresh


def test_due_when_the_dossier_went_stale(client, ai):
    old = datetime.now(timezone.utc) - timedelta(days=45)
    _contact("Застаріла", interactions=1, ai_dossier_updated_at=old)
    with SessionLocal() as db:
        due = [c.first_name for c in insights.due_for_consolidation(db)]
    assert due == ["Застаріла"]


def test_nothing_new_means_nothing_due(client, ai):
    with SessionLocal() as db:
        cid = _contact("Тиха", interactions=4)
        contact = db.get(Contact, cid)
        contact.consolidated_count = 4
        contact.ai_dossier_updated_at = datetime.now(timezone.utc)
        db.commit()
        assert insights.due_for_consolidation(db) == []


def test_most_behind_contacts_go_first_and_the_run_is_capped(client, ai, monkeypatch):
    from app.core.config import settings

    _contact("Трохи", interactions=5)
    _contact("Дуже", interactions=12)
    _contact("Середньо", interactions=8)
    monkeypatch.setattr(settings, "consolidate_max_per_run", 2)

    report = insights.run_consolidation()

    assert report["due"] == 3
    assert report["consolidated"] == 2
    with SessionLocal() as db:
        done = {c.first_name for c in db.query(Contact) if c.ai_dossier}
    assert done == {"Дуже", "Середньо"}     # найвідсталіші, «Трохи» чекає на наступний прохід


def test_one_failure_does_not_stop_the_sweep(client, ai, monkeypatch):
    from app.modules.insights import ai as ai_module

    _contact("Проблемна", interactions=7)
    _contact("Нормальна", interactions=6)

    def flaky(contact):
        if contact.first_name == "Проблемна":
            raise RuntimeError("модель впала")
        return "ок"

    monkeypatch.setattr(ai_module, "generate_dossier", flaky)
    report = insights.run_consolidation()

    assert report["failed"] == 1
    assert report["consolidated"] == 1
    with SessionLocal() as db:
        assert db.query(Contact).filter(Contact.first_name == "Нормальна").one().ai_dossier == "ок"


def test_the_button_and_the_job_share_one_path(client, ai):
    """POST /dossier тепер теж витягає факти і рухає лічильник."""
    cid = _contact(interactions=2)
    client.post(f"/api/contacts/{cid}/dossier")
    with SessionLocal() as db:
        contact = db.get(Contact, cid)
        assert contact.consolidated_count == 2
        assert db.query(ContactFact).count() == 2

    facts = client.post(f"/api/contacts/{cid}/facts/extract").json()
    assert len(facts) == 2   # ідемпотентно — дублів немає
