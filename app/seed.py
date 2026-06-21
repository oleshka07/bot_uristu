"""Seed the database with sample contacts so the app is explorable on first run.

Usage:  python -m app.seed
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from . import crud, models, schemas
from .database import SessionLocal, init_db


def _ago(days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)


SAMPLE = [
    dict(
        contact=schemas.ContactCreate(
            first_name="Olena",
            last_name="Kovalenko",
            relationship_type=models.Relationship.client,
            contact_frequency=models.Frequency.monthly,
            company="SwipeScape",
            position="Head of Product",
            location="Kyiv",
            email="olena@example.com",
            linkedin_url="https://www.linkedin.com/in/example-olena",
            birth_date=date(1990, 7, 12),
            tags=["product", "key-account"],
            notes="Met at the 2023 SaaS conference. Loves climbing and good coffee.",
        ),
        interactions=[
            (45, models.Channel.meeting, 0.8, "Quarterly review — very positive."),
            (120, models.Channel.email, 0.3, "Contract renewal discussion."),
        ],
    ),
    dict(
        contact=schemas.ContactCreate(
            first_name="Marcus",
            last_name="Bauer",
            relationship_type=models.Relationship.investor,
            contact_frequency=models.Frequency.quarterly,
            company="Northbridge Capital",
            position="Partner",
            location="Berlin",
            twitter_url="https://x.com/example-marcus",
            tags=["fundraising"],
            notes="Interested in B2B SaaS. Prefers concise updates.",
        ),
        interactions=[
            (10, models.Channel.message, 0.5, "Shared monthly metrics."),
        ],
    ),
    dict(
        contact=schemas.ContactCreate(
            first_name="Sofia",
            last_name="Rossi",
            relationship_type=models.Relationship.friend,
            contact_frequency=models.Frequency.biweekly,
            location="Milan",
            instagram_url="https://www.instagram.com/example-sofia",
            birth_date=date(1992, 3, 28),
            tags=["close-friend"],
            notes="University friend. Recently moved cities.",
        ),
        interactions=[
            (40, models.Channel.call, 0.9, "Long catch-up call."),
        ],
    ),
    dict(
        contact=schemas.ContactCreate(
            first_name="David",
            last_name="Chen",
            relationship_type=models.Relationship.mentor,
            contact_frequency=models.Frequency.monthly,
            company="Former CTO",
            position="Advisor",
            location="San Francisco",
            tags=["advice", "tech"],
            notes="Generous with time. Great on scaling engineering teams.",
        ),
        interactions=[],
    ),
    dict(
        contact=schemas.ContactCreate(
            first_name="Anna",
            last_name="Nowak",
            relationship_type=models.Relationship.colleague,
            contact_frequency=models.Frequency.weekly,
            company="SwipeScape",
            position="Designer",
            tags=["design", "team"],
        ),
        interactions=[
            (3, models.Channel.message, 0.6, "Reviewed new mockups."),
            (9, models.Channel.meeting, 0.4, "Sprint planning."),
        ],
    ),
]


def run() -> None:
    init_db()
    db = SessionLocal()
    try:
        if db.query(models.Contact).count() > 0:
            print("Database already has contacts; skipping seed.")
            return
        for item in SAMPLE:
            contact = crud.create_contact(db, item["contact"])
            for days, channel, sentiment, summary in item["interactions"]:
                crud.add_interaction(
                    db,
                    contact,
                    schemas.InteractionIn(
                        occurred_at=_ago(days),
                        channel=channel,
                        sentiment=sentiment,
                        summary=summary,
                    ),
                )
        print(f"Seeded {len(SAMPLE)} sample contacts.")
    finally:
        db.close()


if __name__ == "__main__":
    run()
