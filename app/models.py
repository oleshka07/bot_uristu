"""SQLAlchemy ORM models — the relationship database.

Designed so an AI can read a contact's whole story in one object graph:
profile + interactions + key dates + detected life events + social snapshots.
"""

from __future__ import annotations

import enum
from datetime import date, datetime, timezone

from sqlalchemy import (
    Column,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ── Enumerations ─────────────────────────────────────────────────────────────


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


class Channel(str, enum.Enum):
    call = "call"
    message = "message"
    email = "email"
    meeting = "meeting"
    social = "social"
    event = "event"
    other = "other"


class Direction(str, enum.Enum):
    outbound = "outbound"
    inbound = "inbound"


class LifeEventStatus(str, enum.Enum):
    new = "new"
    acknowledged = "acknowledged"
    acted = "acted"
    dismissed = "dismissed"


# ── Association table: contacts ↔ tags ───────────────────────────────────────

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


# ── Core: Contact ────────────────────────────────────────────────────────────


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

    # Social links
    instagram_url: Mapped[str | None] = mapped_column(String(300), nullable=True)
    facebook_url: Mapped[str | None] = mapped_column(String(300), nullable=True)
    linkedin_url: Mapped[str | None] = mapped_column(String(300), nullable=True)
    twitter_url: Mapped[str | None] = mapped_column(String(300), nullable=True)
    youtube_url: Mapped[str | None] = mapped_column(String(300), nullable=True)
    github_url: Mapped[str | None] = mapped_column(String(300), nullable=True)
    website_url: Mapped[str | None] = mapped_column(String(300), nullable=True)

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

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

    # Relationships
    tags: Mapped[list[Tag]] = relationship(
        secondary=contact_tags, back_populates="contacts", lazy="selectin"
    )
    key_dates: Mapped[list["KeyDate"]] = relationship(
        back_populates="contact", cascade="all, delete-orphan", lazy="selectin"
    )
    interactions: Mapped[list["Interaction"]] = relationship(
        back_populates="contact",
        cascade="all, delete-orphan",
        order_by="Interaction.occurred_at.desc()",
        lazy="selectin",
    )
    life_events: Mapped[list["LifeEvent"]] = relationship(
        back_populates="contact",
        cascade="all, delete-orphan",
        order_by="LifeEvent.event_date.desc()",
        lazy="selectin",
    )
    social_snapshots: Mapped[list["SocialSnapshot"]] = relationship(
        back_populates="contact",
        cascade="all, delete-orphan",
        order_by="SocialSnapshot.fetched_at.desc()",
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


class Interaction(Base):
    __tablename__ = "interactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    contact_id: Mapped[int] = mapped_column(
        ForeignKey("contacts.id", ondelete="CASCADE"), index=True
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
    channel: Mapped[Channel] = mapped_column(Enum(Channel), default=Channel.message)
    direction: Mapped[Direction] = mapped_column(
        Enum(Direction), default=Direction.outbound
    )
    # Sentiment in [-1, 1]; feeds warmth scoring.
    sentiment: Mapped[float] = mapped_column(Float, default=0.0)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Provenance / de-duplication for auto-synced interactions.
    source: Mapped[str] = mapped_column(String(40), default="manual")  # manual / gmail / gcal
    external_id: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)

    contact: Mapped[Contact] = relationship(back_populates="interactions")

    __table_args__ = (
        UniqueConstraint("contact_id", "external_id", name="uq_interaction_external"),
    )


class LifeEvent(Base):
    """A significant event detected (or recorded) for a contact — a moment
    worth reaching out about (new job, baby, marriage, birthday milestone)."""

    __tablename__ = "life_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    contact_id: Mapped[int] = mapped_column(
        ForeignKey("contacts.id", ondelete="CASCADE"), index=True
    )
    event_type: Mapped[str] = mapped_column(String(80))  # e.g. new_job, birth, marriage
    title: Mapped[str] = mapped_column(String(240))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    event_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    source: Mapped[str] = mapped_column(String(80), default="manual")  # manual / instagram / ai
    status: Mapped[LifeEventStatus] = mapped_column(
        Enum(LifeEventStatus), default=LifeEventStatus.new
    )
    suggested_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    contact: Mapped[Contact] = relationship(back_populates="life_events")


class SocialSnapshot(Base):
    """Raw data captured from a social profile, kept as JSON-ish text so the
    AI can read it and so we can re-process it later as connectors improve."""

    __tablename__ = "social_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    contact_id: Mapped[int] = mapped_column(
        ForeignKey("contacts.id", ondelete="CASCADE"), index=True
    )
    platform: Mapped[str] = mapped_column(String(40))  # instagram / linkedin / ...
    url: Mapped[str] = mapped_column(String(400))
    title: Mapped[str | None] = mapped_column(String(400), nullable=True)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    contact: Mapped[Contact] = relationship(back_populates="social_snapshots")

    __table_args__ = (UniqueConstraint("contact_id", "url", name="uq_contact_social_url"),)


class IntegrationToken(Base):
    """OAuth credentials for an external integration (e.g. Google).

    Single-user internal tool: one token per provider. Stored as the JSON the
    Google client library serialises (includes the refresh token)."""

    __tablename__ = "integration_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    token_json: Mapped[str] = mapped_column(Text)
    account_email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    last_sync_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
