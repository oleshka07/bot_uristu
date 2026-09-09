"""Пошта як черга дій: синк тредів, класифікація, чернетки, відправка."""

from datetime import datetime, timedelta, timezone

import pytest

from app.core.database import SessionLocal
from app.modules.inbox import service as inbox
from app.modules.inbox.models import EmailThread
from app.modules.telegram_bot import handlers


def _thread(tid="t1", **kw):
    row = {
        "thread_id": tid,
        "message_id": f"{tid}-m1",
        "subject": "Комерційна пропозиція",
        "from_email": "maria@example.com",
        "from_name": "Марія",
        "snippet": "Надішліть, будь ласка, умови",
        "body": "Доброго дня. Надішліть, будь ласка, умови співпраці.",
        "last_at": datetime.now(timezone.utc) - timedelta(hours=2),
        "last_from_me": False,
        "messages": 1,
    }
    row.update(kw)
    return row


@pytest.fixture
def gmail(monkeypatch):
    """Підмінює Gmail: віддає задані треди, записує чернетки й відправку."""
    from app.modules.integrations.google import client as google

    state = {"threads": [], "drafts": [], "sent": [], "draft_ok": True}

    monkeypatch.setattr(google, "fetch_inbox_threads", lambda db, **kw: state["threads"])

    def create_draft(db, *, thread_id, to, subject, body):
        if not state["draft_ok"]:
            return None
        state["drafts"].append({"thread_id": thread_id, "to": to, "body": body})
        return f"draft-{len(state['drafts'])}"

    def send_email(db, to, subject, body_html, *, thread_id=None, plain=False):
        state["sent"].append({"to": to, "subject": subject, "body": body_html,
                              "thread_id": thread_id})
        return True

    monkeypatch.setattr(google, "create_draft", create_draft)
    monkeypatch.setattr(google, "send_email", send_email)
    return state


@pytest.fixture
def ai(monkeypatch):
    """Підмінює модель: керований вердикт і передбачувана чернетка."""
    from app.modules.insights import ai as ai_module

    state = {
        "verdict": {"needs_reply": True, "urgency": "high", "topic": "просить умови"},
        "draft": "Надсилаю умови у вкладенні.",
    }
    monkeypatch.setattr(ai_module, "triage_email", lambda *a, **kw: state["verdict"])
    monkeypatch.setattr(ai_module, "draft_email_reply", lambda *a, **kw: state["draft"])
    return state


def test_sync_creates_threads_and_matches_a_known_contact(client, gmail):
    client.post("/api/contacts", json={"first_name": "Марія", "email": "maria@example.com"})
    gmail["threads"] = [_thread()]

    with SessionLocal() as db:
        report = inbox.sync(db)
        assert report["added"] == 1
        row = db.query(EmailThread).one()
        assert row.status == "waiting"
        assert row.contact_id is not None       # звʼязали з людиною за поштою
        assert row.subject == "Комерційна пропозиція"


def test_unknown_sender_still_lands_in_the_queue(client, gmail):
    """Головна діра старого синку: листи від невідомих не існували."""
    gmail["threads"] = [_thread(from_email="stranger@example.com")]

    with SessionLocal() as db:
        inbox.sync(db)
        row = db.query(EmailThread).one()
        assert row.contact_id is None
        assert row.status == "waiting"


def test_thread_i_answered_last_is_not_waiting(client, gmail):
    gmail["threads"] = [_thread(last_from_me=True)]

    with SessionLocal() as db:
        inbox.sync(db)
        assert db.query(EmailThread).one().status == "answered"


def test_new_letter_reopens_the_thread_and_drops_the_stale_draft(client, gmail, ai):
    gmail["threads"] = [_thread()]
    with SessionLocal() as db:
        inbox.sync(db)
        inbox.classify_pending(db)
        inbox.draft_pending(db)
        row = db.query(EmailThread).one()
        assert row.draft_text
        inbox.set_status(db, row, "answered")

    # Прийшов новий лист у той самий тред.
    gmail["threads"] = [_thread(message_id="t1-m2", messages=2)]
    with SessionLocal() as db:
        report = inbox.sync(db)
        assert report["reopened"] == 1
        row = db.query(EmailThread).one()
        assert row.status == "waiting"
        # Стара чернетка відповідала на попереднє повідомлення — вона недійсна.
        assert row.draft_text is None
        assert row.classified_at is None


def test_classification_marks_what_waits_for_an_answer(client, gmail, ai):
    gmail["threads"] = [_thread()]
    with SessionLocal() as db:
        inbox.sync(db)
        assert inbox.classify_pending(db) == 1
        row = db.query(EmailThread).one()
        assert row.needs_reply is True
        assert row.urgency == "high"
        assert row.topic == "просить умови"
        # Другий прохід не переплачує за вже класифіковане.
        assert inbox.classify_pending(db) == 0


def test_newsletters_do_not_get_drafts(client, gmail, ai):
    ai["verdict"] = {"needs_reply": False, "urgency": "low", "topic": "розсилка"}
    gmail["threads"] = [_thread()]
    with SessionLocal() as db:
        inbox.sync(db)
        inbox.classify_pending(db)
        assert inbox.draft_pending(db) == 0
        assert db.query(EmailThread).one().draft_text is None
        assert inbox.waiting(db) == []


def test_draft_goes_into_gmail_drafts(client, gmail, ai):
    gmail["threads"] = [_thread()]
    with SessionLocal() as db:
        inbox.sync(db)
        inbox.classify_pending(db)
        inbox.draft_pending(db)
        row = db.query(EmailThread).one()

    assert row.draft_text == "Надсилаю умови у вкладенні."
    assert row.draft_id == "draft-1"
    assert gmail["drafts"][0]["thread_id"] == "t1"   # у той самий тред
    assert gmail["drafts"][0]["to"] == "maria@example.com"


def test_missing_gmail_scope_keeps_the_draft_here(client, gmail, ai):
    """Без gmail.compose чернетка все одно має бути — просто не в Gmail."""
    gmail["draft_ok"] = False
    gmail["threads"] = [_thread()]
    with SessionLocal() as db:
        inbox.sync(db)
        inbox.classify_pending(db)
        inbox.draft_pending(db)
        row = db.query(EmailThread).one()

    assert row.draft_text
    assert row.draft_id is None


def test_queue_puts_urgent_first_then_the_longest_waiting(client, gmail, monkeypatch):
    from app.modules.insights import ai as ai_module

    verdicts = {
        "t1": {"needs_reply": True, "urgency": "normal", "topic": "старе"},
        "t2": {"needs_reply": True, "urgency": "high", "topic": "терміново"},
        "t3": {"needs_reply": True, "urgency": "normal", "topic": "свіже"},
    }
    monkeypatch.setattr(
        ai_module, "triage_email",
        lambda subject, sender, body: verdicts[subject],
    )
    now = datetime.now(timezone.utc)
    gmail["threads"] = [
        _thread("t1", subject="t1", last_at=now - timedelta(days=5)),
        _thread("t2", subject="t2", last_at=now - timedelta(hours=1)),
        _thread("t3", subject="t3", last_at=now - timedelta(days=1)),
    ]
    with SessionLocal() as db:
        inbox.sync(db)
        inbox.classify_pending(db)
        assert [t.subject for t in inbox.waiting(db)] == ["t2", "t1", "t3"]


def test_sending_a_reply_closes_the_thread(client, gmail, ai):
    gmail["threads"] = [_thread()]
    with SessionLocal() as db:
        inbox.sync(db)
        inbox.classify_pending(db)
        inbox.draft_pending(db)
        row = db.query(EmailThread).one()
        assert inbox.send_reply(db, row) is True
        db.refresh(row)
        assert row.status == "answered"

    sent = gmail["sent"][0]
    assert sent["to"] == "maria@example.com"
    assert sent["thread_id"] == "t1"              # відповідь лишається в тредi
    assert sent["subject"].startswith("Re: ")


def test_api_shows_the_queue_and_its_numbers(client, gmail, ai):
    gmail["threads"] = [_thread()]
    report = client.post("/api/inbox/sync").json()
    assert report["added"] == 1 and report["classified"] == 1

    queue = client.get("/api/inbox").json()
    assert len(queue) == 1
    item = queue[0]
    assert item["urgency"] == "high"
    assert item["draft_text"] == "Надсилаю умови у вкладенні."
    assert item["in_gmail"] is True

    stats = client.get("/api/inbox/stats").json()
    assert stats == {"waiting": 1, "urgent": 1, "stale": 0, "drafted": 1, "in_gmail": 1}

    client.patch(f"/api/inbox/{item['id']}", json={"status": "ignored"})
    assert client.get("/api/inbox").json() == []


class FakeClient:
    def __init__(self):
        self.messages = []
        self.answers = []

    def send_message(self, chat, text, **kw):
        self.messages.append((text, kw.get("reply_markup")))

    def answer_callback(self, cb_id, text=None):
        self.answers.append(text)


@pytest.fixture
def bot(monkeypatch):
    monkeypatch.setattr(handlers, "_admin_id", lambda: 42)
    return FakeClient()


def test_bot_lists_the_queue_and_opens_a_letter(client, gmail, ai, bot):
    gmail["threads"] = [_thread()]
    client.post("/api/inbox/sync")
    thread_pk = client.get("/api/inbox").json()[0]["id"]

    handlers._handle_command(bot, 42, "/inbox")
    text, _ = bot.messages[-1]
    assert "Чекають відповіді: 1" in text
    assert "просить умови" in text

    handlers._handle_command(bot, 42, f"/mail {thread_pk}")
    text, markup = bot.messages[-1]
    assert "Надсилаю умови у вкладенні." in text
    labels = [b["text"] for b in markup["inline_keyboard"][0]]
    assert labels == ["Надіслати", "Переписати", "Пропустити"]


def test_send_button_sends_the_draft(client, gmail, ai, bot):
    gmail["threads"] = [_thread()]
    client.post("/api/inbox/sync")
    thread_pk = client.get("/api/inbox").json()[0]["id"]

    handlers._handle_mail_callback(bot, "cb1", f"m:s:{thread_pk}", 42)
    assert bot.answers[-1] == "Надіслано"
    assert gmail["sent"][0]["to"] == "maria@example.com"
    assert client.get("/api/inbox").json() == []


def test_skip_button_takes_it_out_of_the_queue(client, gmail, ai, bot):
    gmail["threads"] = [_thread()]
    client.post("/api/inbox/sync")
    thread_pk = client.get("/api/inbox").json()[0]["id"]

    handlers._handle_mail_callback(bot, "cb1", f"m:x:{thread_pk}", 42)
    assert bot.answers[-1] == "Прибрав з черги"
    assert client.get("/api/inbox").json() == []


def test_send_endpoint_sends_and_closes(client, gmail, ai):
    gmail["threads"] = [_thread()]
    client.post("/api/inbox/sync")
    thread_pk = client.get("/api/inbox").json()[0]["id"]

    sent = client.post(f"/api/inbox/{thread_pk}/send").json()
    assert sent["status"] == "answered"
    assert gmail["sent"][0]["thread_id"] == "t1"


def test_send_without_a_draft_is_rejected(client, gmail, ai):
    ai["draft"] = None
    gmail["threads"] = [_thread()]
    client.post("/api/inbox/sync")
    thread_pk = client.get("/api/inbox").json()[0]["id"]

    assert client.post(f"/api/inbox/{thread_pk}/send").status_code == 502
