from datetime import datetime, timedelta, timezone

from app import models, warmth


def _contact(freq, created_days_ago=0, last_days_ago=None):
    c = models.Contact(first_name="X", contact_frequency=freq)
    c.created_at = datetime.now(timezone.utc) - timedelta(days=created_days_ago)
    if last_days_ago is not None:
        c.last_contacted_at = datetime.now(timezone.utc) - timedelta(days=last_days_ago)
    return c


def test_target_days():
    assert warmth.target_days(models.Frequency.weekly) == 7
    assert warmth.target_days(models.Frequency.monthly) == 30


def test_status_thresholds():
    assert warmth.status_for_score(90) == "hot"
    assert warmth.status_for_score(50) == "warm"
    assert warmth.status_for_score(30) == "cooling"
    assert warmth.status_for_score(10) == "cold"


def test_recent_contact_is_warm():
    c = _contact(models.Frequency.weekly, last_days_ago=0)
    score, status = warmth.compute_warmth(c)
    assert score > 70
    assert status in ("hot", "warm")
    assert not warmth.is_due(c)


def test_stale_contact_is_cold_and_due():
    c = _contact(models.Frequency.weekly, created_days_ago=120, last_days_ago=120)
    score, _ = warmth.compute_warmth(c)
    assert score < 40
    assert warmth.is_due(c)
    assert warmth.overdue_ratio(c) > 1
