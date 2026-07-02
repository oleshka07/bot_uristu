"""Telegram export importer: chat matching, style examples, backfill dedupe."""

import json
from datetime import datetime, timedelta, timezone


def _write_export(tmp_path, chats):
    path = tmp_path / "result.json"
    path.write_text(
        json.dumps({"chats": {"list": chats}}, ensure_ascii=False), encoding="utf-8"
    )
    return str(path)


def _chat(chat_id, name, messages):
    return {
        "type": "personal_chat",
        "id": chat_id,
        "name": name,
        "messages": messages,
    }


def _msg(mid, from_user_id, text, days_ago=10):
    dt = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return {
        "id": mid,
        "type": "message",
        "date": dt.isoformat(),
        "from_id": f"user{from_user_id}",
        "text": text,
    }


def test_import_style_and_backfill(client, tmp_path):
    from app.core.database import SessionLocal
    from app.modules.contacts.models import Contact
    from app.modules.integrations.tgexport.importer import import_export

    with SessionLocal() as db:
        c = Contact(first_name="Ліза", telegram_chat_id=5001)
        db.add(c)
        db.commit()
        cid = c.id

        export = _write_export(
            tmp_path,
            [
                _chat(
                    5001,
                    "Ліза",
                    [
                        _msg(1, 5001, "Привіт! Як справи з контактом капітана?", 12),
                        _msg(2, 99, "Привіт-привіт! Все вийшло, дякую тобі велике 🙏", 11),
                        _msg(3, 99, "Давай на каву наступного тижня, я пригощаю", 10),
                    ],
                ),
                # Group chats are ignored.
                {"type": "private_group", "id": 7, "name": "Друзі", "messages": []},
                # Unknown person — skipped (only enrich existing contacts).
                _chat(6002, "Невідомий", [_msg(9, 6002, "хто ти", 5)]),
            ],
        )
        report = import_export(db, export, backfill=True)

        assert report.chats_seen == 2
        assert report.chats_matched == 1
        assert report.interactions_added == 3
        assert report.style_contacts == 1

        c = db.get(Contact, cid)
        examples = json.loads(c.style_examples)
        # Only MY messages (from_id != chat user), 15..400 chars.
        assert examples == [
            "Привіт-привіт! Все вийшло, дякую тобі велике 🙏",
            "Давай на каву наступного тижня, я пригощаю",
        ]
        directions = [i.direction.value for i in c.interactions]
        assert directions.count("outbound") == 2
        assert directions.count("inbound") == 1

        # Re-import is idempotent (external ids dedupe).
        report2 = import_export(db, export, backfill=True)
        assert report2.interactions_added == 0


def test_import_dedupes_near_duplicates_from_chater(client, tmp_path):
    from app.core.database import SessionLocal
    from app.modules.contacts.models import Contact
    from app.modules.integrations.tgexport.importer import import_export
    from app.modules.interactions.models import Channel, Direction, Interaction

    with SessionLocal() as db:
        c = Contact(first_name="Дубль", telegram_chat_id=5002)
        db.add(c)
        db.flush()
        when = datetime.now(timezone.utc) - timedelta(days=10)
        # Same message already imported from the Chater DB (different id space).
        db.add(
            Interaction(
                contact_id=c.id,
                occurred_at=when + timedelta(seconds=40),
                channel=Channel.message,
                direction=Direction.inbound,
                summary="те саме повідомлення",
                source="telegram",
                external_id="tg:777",
            )
        )
        db.commit()
        cid = c.id

        export = _write_export(
            tmp_path,
            [_chat(5002, "Дубль", [_msg(50, 5002, "те саме повідомлення", 10)])],
        )
        report = import_export(db, export, backfill=True)
        assert report.interactions_added == 0  # near-duplicate skipped

        c = db.get(Contact, cid)
        assert len(c.interactions) == 1


def test_match_by_name_backfills_chat_id(client, tmp_path):
    from app.core.database import SessionLocal
    from app.modules.contacts.models import Contact
    from app.modules.integrations.tgexport.importer import import_export

    with SessionLocal() as db:
        c = Contact(first_name="Іван", last_name="Безайді")  # no telegram_chat_id
        db.add(c)
        db.commit()
        cid = c.id

        export = _write_export(
            tmp_path,
            [_chat(5003, "Іван Безайді", [_msg(1, 99, "Привіт, Іване! Як твій проєкт?", 3)])],
        )
        report = import_export(db, export, backfill=False)
        assert report.chats_matched == 1

        c = db.get(Contact, cid)
        assert c.telegram_chat_id == 5003  # backfilled → Business proxy works
        assert c.style_examples  # my message captured as style example


def test_create_all_adds_people_i_wrote_to(client, tmp_path):
    from app.core.database import SessionLocal
    from sqlalchemy import select
    from app.modules.contacts.models import Contact
    from app.modules.integrations.tgexport.importer import import_export

    with SessionLocal() as db:
        export = _write_export(
            tmp_path,
            [
                # I wrote to this person → contact created with history.
                _chat(
                    8001,
                    "Нова Людина",
                    [
                        _msg(1, 8001, "Привіт, ти з конференції?", 20),
                        _msg(2, 99, "Так, я! Радий знайомству, наберу завтра", 19),
                    ],
                ),
                # Bot chat → never auto-created.
                _chat(8002, "SomeServiceBot", [_msg(3, 99, "Старт бота і команди тут", 5)]),
                # One-way spam (I never replied) → skipped.
                _chat(8003, "Спамер", [_msg(4, 8003, "Купіть наші курси зі знижкою", 5)]),
            ],
        )
        report = import_export(db, export, backfill=True, create_missing=True)
        assert report.contacts_created == 1
        assert report.interactions_added == 2

        c = db.scalar(select(Contact).where(Contact.telegram_chat_id == 8001))
        assert c is not None
        assert c.full_name == "Нова Людина"
        assert c.contact_frequency.value == "quarterly"
        assert "tg-export" in [t.name for t in c.tags]
        assert db.scalar(select(Contact).where(Contact.telegram_chat_id == 8002)) is None
        assert db.scalar(select(Contact).where(Contact.telegram_chat_id == 8003)) is None

        # Idempotent: run again → matches, creates nothing new.
        report2 = import_export(db, export, backfill=True, create_missing=True)
        assert report2.contacts_created == 0
        assert report2.interactions_added == 0
