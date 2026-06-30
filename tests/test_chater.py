from sqlalchemy import func, select

from app import models
from app.integrations import chater


def _chater_contact(db, tag, first, last, telegram=None, messages=0):
    c = models.Contact(first_name=first, last_name=last, telegram=telegram)
    c.tags = [tag]
    db.add(c)
    db.flush()
    for i in range(messages):
        db.add(
            models.Interaction(
                contact_id=c.id,
                channel=models.Channel.message,
                direction=models.Direction.inbound,
                source="telegram",
                external_id=f"tg:{c.id}:{i}",
            )
        )
    db.flush()
    return c


def test_dedupe_collapses_duplicates(db):
    tag = models.Tag(name="chater")
    db.add(tag)
    db.flush()
    # Two duplicates with no channel, one with telegram (also duplicated).
    _chater_contact(db, tag, "Inna", "S")
    _chater_contact(db, tag, "Inna", "S")
    _chater_contact(db, tag, "Petro", "T", telegram="tripaylo", messages=2)
    _chater_contact(db, tag, "Petro", "T", telegram="tripaylo", messages=2)
    _chater_contact(db, tag, "Oleg", "U")
    db.commit()

    assert db.scalar(select(func.count()).select_from(models.Contact)) == 5
    removed = chater.dedupe(db)
    assert removed == 2
    assert db.scalar(select(func.count()).select_from(models.Contact)) == 3

    # Running again is a no-op.
    assert chater.dedupe(db) == 0


def test_duplicate_count(db):
    tag = models.Tag(name="chater")
    db.add(tag)
    db.flush()
    _chater_contact(db, tag, "A", "A")
    _chater_contact(db, tag, "A", "A")
    db.commit()
    info = chater.duplicate_count(db)
    assert info["unique"] == 1
    assert info["duplicate_extras"] == 1
