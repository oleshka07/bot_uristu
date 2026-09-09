"""Contacts domain models: the person and their profile data.

Contact is the aggregate root; Tag and KeyDate are its value objects.
Relationships to Interaction / LifeEvent / SocialSnapshot (other modules) are
declared by string, so this module imports no sibling module.
"""

from __future__ import annotations

import enum
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Column,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    String,
    Table,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, utcnow


class Relationship(str, enum.Enum):
    family = "family"
    friend = "friend"
    colleague = "colleague"
    client = "client"
    partner = "partner"
    mentor = "mentor"
    investor = "investor"
    acquaintance = "acquaintance"
    other = "other"


class Frequency(str, enum.Enum):
    """Desired cadence of contact. Value maps to target days in warmth.py."""

    weekly = "weekly"
    biweekly = "biweekly"
    monthly = "monthly"
    quarterly = "quarterly"
    biannual = "biannual"
    yearly = "yearly"


contact_tags = Table(
    "contact_tags",
    Base.metadata,
    Column("contact_id", ForeignKey("contacts.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
)


class Tag(Base):
    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True, index=True)

    contacts: Mapped[list["Contact"]] = relationship(
        secondary=contact_tags, back_populates="tags"
    )


class Contact(Base):
    __tablename__ = "contacts"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    # Identity
    first_name: Mapped[str] = mapped_column(String(120))
    last_name: Mapped[str | None] = mapped_column(String(120), nullable=True)

    # Classification
    relationship_type: Mapped[Relationship] = mapped_column(
        Enum(Relationship), default=Relationship.acquaintance
    )
    contact_frequency: Mapped[Frequency] = mapped_column(
        Enum(Frequency), default=Frequency.monthly
    )

    # Profile
    company: Mapped[str | None] = mapped_column(String(200), nullable=True)
    position: Mapped[str | None] = mapped_column(String(200), nullable=True)
    location: Mapped[str | None] = mapped_column(String(200), nullable=True)
    birth_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Contact details
    email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(60), nullable=True)
    whatsapp: Mapped[str | None] = mapped_column(String(60), nullable=True)
    telegram: Mapped[str | None] = mapped_column(String(120), nullable=True)
    viber: Mapped[str | None] = mapped_column(String(60), nullable=True)

    # Telegram numeric chat id — the stable key the Business proxy uses to
    # match an incoming DM to a contact (usernames change, ids don't).
    telegram_chat_id: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True, index=True
    )

    # Preferred communication tone with this person (e.g. "дружній",
    # "діловий") — steers AI reply drafts. Imported from Chater.
    tone: Mapped[str | None] = mapped_column(String(80), nullable=True)

    # Stop-list: one-off contacts the outreach queue must never suggest.
    do_not_contact: Mapped[bool] = mapped_column(default=False)

    # "I answer this person myself": keep logging their messages and context,
    # but don't auto-draft replies — just a quiet heads-up instead.
    auto_reply_paused: Mapped[bool] = mapped_column(default=False)

    # Importance for queue priority: 0=auto (derived from dialogue depth),
    # 1=низька, 2=звичайна, 3=висока (ties to the owner's goals/projects).
    importance: Mapped[int] = mapped_column(default=0)

    # JSON array of the owner's real recent messages TO this person
    # (from the Telegram export) — few-shot style examples for drafts.
    style_examples: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Social links
    instagram_url: Mapped[str | None] = mapped_column(String(300), nullable=True)
    facebook_url: Mapped[str | None] = mapped_column(String(300), nullable=True)
    linkedin_url: Mapped[str | None] = mapped_column(String(300), nullable=True)
    twitter_url: Mapped[str | None] = mapped_column(String(300), nullable=True)
    youtube_url: Mapped[str | None] = mapped_column(String(300), nullable=True)
    github_url: Mapped[str | None] = mapped_column(String(300), nullable=True)
    website_url: Mapped[str | None] = mapped_column(String(300), nullable=True)

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Stable external identity for imported contacts (e.g. "chater:42"), used
    # to de-duplicate on re-import even when there is no email/telegram.
    external_ref: Mapped[str | None] = mapped_column(
        String(120), nullable=True, index=True
    )

    # Derived relationship intelligence
    warmth_score: Mapped[float] = mapped_column(Float, default=50.0)
    warmth_status: Mapped[str] = mapped_column(String(20), default="warm")
    last_contacted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # AI-generated
    ai_dossier: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_dossier_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Скільки взаємодій було на момент останньої консолідації памʼяті.
    # Лічильник, а не час: підтягнуті заднім числом листи мають старий
    # occurred_at і за часом «новими» не виглядали б.
    consolidated_count: Mapped[int] = mapped_column(default=0)

    # Relationships (string-based → no imports of sibling modules)
    tags: Mapped[list[Tag]] = relationship(
        secondary=contact_tags, back_populates="contacts", lazy="selectin"
    )
    key_dates: Mapped[list["KeyDate"]] = relationship(
        back_populates="contact", cascade="all, delete-orphan", lazy="selectin"
    )
    interactions: Mapped[list["Interaction"]] = relationship(  # noqa: F821
        back_populates="contact",
        cascade="all, delete-orphan",
        order_by="Interaction.occurred_at.desc()",
        lazy="selectin",
    )
    life_events: Mapped[list["LifeEvent"]] = relationship(  # noqa: F821
        back_populates="contact",
        cascade="all, delete-orphan",
        order_by="LifeEvent.event_date.desc()",
        lazy="selectin",
    )
    social_snapshots: Mapped[list["SocialSnapshot"]] = relationship(  # noqa: F821
        back_populates="contact",
        cascade="all, delete-orphan",
        order_by="SocialSnapshot.fetched_at.desc()",
        lazy="selectin",
    )
    facts: Mapped[list["ContactFact"]] = relationship(  # noqa: F821
        back_populates="contact",
        cascade="all, delete-orphan",
        order_by="ContactFact.created_at.desc()",
        lazy="selectin",
    )

    @property
    def full_name(self) -> str:
        return " ".join(p for p in [self.first_name, self.last_name] if p)


class KeyDate(Base):
    __tablename__ = "key_dates"

    id: Mapped[int] = mapped_column(primary_key=True)
    contact_id: Mapped[int] = mapped_column(
        ForeignKey("contacts.id", ondelete="CASCADE"), index=True
    )
    date: Mapped[date] = mapped_column(Date)
    label: Mapped[str] = mapped_column(String(160))

    contact: Mapped[Contact] = relationship(back_populates="key_dates")
