"""Telegram Business proxy: contact matching, draft lifecycle, send-as-user."""

from app.modules.telegram_bot import service
from app.modules.telegram_bot.handlers import dispatch
from app.modules.telegram_bot.models import DraftStatus


class FakeClient:
    """Records outgoing Bot API calls; returns canned results."""

    def __init__(self):
        self.sent = []
        self.edited = []
        self.deleted = []
        self.callbacks = []
        self._next_message_id = 100

    configured = True

    def send_message(self, chat_id, text, **kw):
        self._next_message_id += 1
        self.sent.append({"chat_id": chat_id, "text": text, **kw})
        return {"message_id": self._next_message_id, "chat": {"id": chat_id}}

    def edit_message_text(self, chat_id, message_id, text, **kw):
        self.edited.append({"chat_id": chat_id, "message_id": message_id, "text": text})
        return {"message_id": message_id}

    def delete_message(self, chat_id, message_id):
        self.deleted.append({"chat_id": chat_id, "message_id": message_id})
        return True

    def answer_callback(self, cb_id, text=None):
        self.callbacks.append(text)
        return True

    def download_file(self, file_id):
        return None

    def call(self, method, **kw):
        return {}


def _business_update(chat_id=555001, text="Привіт! Як справи?", msg_id=7):
    return {
        "update_id": 1,
        "business_message": {
            "message_id": msg_id,
            "business_connection_id": "bc-1",
            "chat": {"id": chat_id, "first_name": "Олег", "username": "oleh_test"},
            "from": {"id": chat_id, "first_name": "Олег", "username": "oleh_test"},
            "text": text,
        },
    }


def test_incoming_business_message_creates_contact_draft_and_preview(client, monkeypatch):
    monkeypatch.setattr(
        "app.core.config.settings.telegram_chat_id", "42", raising=False
    )
    fake = FakeClient()
    dispatch(fake, _business_update())

    from app.core.database import SessionLocal
    from app.modules.contacts.models import Contact
    from app.modules.telegram_bot.models import TelegramDraft
    from sqlalchemy import select

    with SessionLocal() as db:
        contact = db.scalar(select(Contact).where(Contact.telegram_chat_id == 555001))
        assert contact is not None
        assert contact.first_name == "Олег"
        assert len(contact.interactions) == 1
        assert contact.interactions[0].direction.value == "inbound"

        draft = db.scalar(select(TelegramDraft))
        assert draft is not None
        assert draft.status == DraftStatus.pending
        assert draft.business_connection_id == "bc-1"
        assert draft.incoming_text == "Привіт! Як справи?"
        # No ANTHROPIC key in tests → no canned draft, admin still notified.
        assert draft.draft_text == ""
        assert draft.admin_message_id is not None

    # Admin preview was sent to chat 42 with the skip/manual buttons.
    assert fake.sent and fake.sent[0]["chat_id"] == 42
    assert "Олег" in fake.sent[0]["text"]


def test_approve_and_send_uses_business_connection(client, monkeypatch):
    monkeypatch.setattr(
        "app.core.config.settings.telegram_chat_id", "42", raising=False
    )
    fake = FakeClient()
    dispatch(fake, _business_update())

    from app.core.database import SessionLocal
    from sqlalchemy import select
    from app.modules.telegram_bot.models import TelegramDraft

    with SessionLocal() as db:
        draft = db.scalar(select(TelegramDraft))
        service.update_draft_text(db, draft, "Все супер, дякую!")
        ok = service.approve_and_send(db, fake, draft)
        assert ok
        assert draft.status == DraftStatus.sent

        outbound = fake.sent[-1]
        assert outbound["chat_id"] == 555001
        assert outbound["business_connection_id"] == "bc-1"
        assert outbound["text"] == "Все супер, дякую!"

        # Outgoing interaction logged against the contact.
        from app.modules.contacts.models import Contact

        contact = db.scalar(select(Contact).where(Contact.telegram_chat_id == 555001))
        directions = [i.direction.value for i in contact.interactions]
        assert "outbound" in directions and "inbound" in directions


def test_send_callback_marks_sent_and_edits_preview(client, monkeypatch):
    monkeypatch.setattr(
        "app.core.config.settings.telegram_chat_id", "42", raising=False
    )
    fake = FakeClient()
    dispatch(fake, _business_update())

    from app.core.database import SessionLocal
    from sqlalchemy import select
    from app.modules.telegram_bot.models import TelegramDraft

    with SessionLocal() as db:
        draft = db.scalar(select(TelegramDraft))
        service.update_draft_text(db, draft, "Ок!")
        draft_id = draft.id
        admin_msg = draft.admin_message_id

    dispatch(
        fake,
        {
            "update_id": 2,
            "callback_query": {
                "id": "cb1",
                "data": f"d:s:{draft_id}",
                "message": {"chat": {"id": 42}, "message_id": admin_msg, "text": "prev"},
            },
        },
    )

    with SessionLocal() as db:
        draft = db.get(TelegramDraft, draft_id)
        assert draft.status == DraftStatus.sent
    assert any("Надіслано" in (c or "") for c in fake.callbacks)


def test_own_outgoing_business_message_logged_not_drafted(client, monkeypatch):
    monkeypatch.setattr(
        "app.core.config.settings.telegram_chat_id", "42", raising=False
    )
    fake = FakeClient()
    update = _business_update()
    # Sender = me (the business account owner), not the chat peer.
    update["business_message"]["from"] = {"id": 42, "first_name": "Степан"}
    update["business_message"]["text"] = "Привіт, тримай файли"
    dispatch(fake, update)

    from app.core.database import SessionLocal
    from sqlalchemy import select
    from app.modules.contacts.models import Contact
    from app.modules.telegram_bot.models import TelegramDraft

    with SessionLocal() as db:
        contact = db.scalar(select(Contact).where(Contact.telegram_chat_id == 555001))
        assert contact is not None
        assert [i.direction.value for i in contact.interactions] == ["outbound"]
        assert db.scalar(select(TelegramDraft)) is None
    assert fake.sent == []  # no admin preview for my own message


def test_business_connection_upsert(client):
    fake = FakeClient()
    dispatch(
        fake,
        {
            "update_id": 3,
            "business_connection": {
                "id": "bc-9",
                "user": {"id": 42},
                "is_enabled": True,
            },
        },
    )
    from app.core.database import SessionLocal
    from sqlalchemy import select
    from app.modules.telegram_bot.models import BusinessConnection

    with SessionLocal() as db:
        conn = db.scalar(
            select(BusinessConnection).where(BusinessConnection.connection_id == "bc-9")
        )
        assert conn is not None and conn.is_enabled and conn.user_chat_id == 42
