"""Relationship warmth engine.

Turns a contact's interaction history + desired cadence into a single
0–100 warmth coefficient and a human-readable status. Also decides who is
"due" for contact. Pure functions — no database, easy to test and for the
AI to reason about.

Lives in the interactions module: warmth is a pure function of a contact's
interaction history. It reads the ``Frequency``/``Contact`` types from the
contacts module but never touches the database.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

from app.modules.contacts.models import Contact, Frequency

# Desired cadence → target number of days between meaningful contacts.
FREQUENCY_DAYS: dict[Frequency, int] = {
    Frequency.weekly: 7,
    Frequency.biweekly: 14,
    Frequency.monthly: 30,
    Frequency.quarterly: 90,
    Frequency.biannual: 182,
    Frequency.yearly: 365,
}


def target_days(frequency: Frequency) -> int:
    return FREQUENCY_DAYS.get(frequency, 30)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def days_since_last_contact(contact: Contact) -> float:
    """Days since the most recent interaction, or since the contact was added
    if there are no interactions yet."""
    reference = _as_aware(contact.last_contacted_at) or _as_aware(contact.created_at)
    if reference is None:
        return 0.0
    delta = _now() - reference
    return max(delta.total_seconds() / 86400.0, 0.0)


def status_for_score(score: float) -> str:
    if score >= 70:
        return "hot"
    if score >= 45:
        return "warm"
    if score >= 25:
        return "cooling"
    return "cold"


def compute_warmth(contact: Contact) -> tuple[float, str]:
    """Return (score 0–100, status).

    Three weighted components:
      * recency   (75%) — exponential decay against the desired cadence.
      * sentiment (15%) — average tone of recorded interactions.
      * consistency (10%) — how many touch-points exist at all.
    """
    tdays = target_days(contact.contact_frequency)
    elapsed = days_since_last_contact(contact)

    # Recency: 100 at "just talked", ~61 at exactly one cadence, ~37 at double.
    recency = 100.0 * math.exp(-elapsed / (2.0 * tdays))

    interactions = contact.interactions or []
    if interactions:
        avg_sentiment = sum(i.sentiment for i in interactions) / len(interactions)
    else:
        avg_sentiment = 0.0
    # Map sentiment [-1, 1] → [0, 100].
    sentiment_component = (avg_sentiment + 1.0) / 2.0 * 100.0

    # Consistency: saturates at 8 interactions.
    consistency_component = min(len(interactions), 8) / 8.0 * 100.0

    score = recency * 0.75 + sentiment_component * 0.15 + consistency_component * 0.10
    score = max(0.0, min(100.0, score))
    return round(score, 1), status_for_score(score)


def is_due(contact: Contact) -> bool:
    """True when the contact is overdue for a touch-point."""
    return days_since_last_contact(contact) >= target_days(contact.contact_frequency)


def overdue_ratio(contact: Contact) -> float:
    """How overdue a contact is: 1.0 == exactly at cadence, >1 == overdue.
    Used to rank who needs attention most."""
    tdays = target_days(contact.contact_frequency)
    if tdays == 0:
        return 0.0
    return days_since_last_contact(contact) / tdays


def refresh(contact: Contact) -> Contact:
    """Recompute and store warmth + last_contacted_at on the contact.
    Call after interactions change. Caller is responsible for committing."""
    if contact.interactions:
        latest = max(
            (_as_aware(i.occurred_at) for i in contact.interactions),
            default=None,
        )
        contact.last_contacted_at = latest
    score, status = compute_warmth(contact)
    contact.warmth_score = score
    contact.warmth_status = status
    return contact
