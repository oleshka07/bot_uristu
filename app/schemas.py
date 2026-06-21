"""Pydantic schemas for the API layer (request/response models)."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from .models import (
    Channel,
    Direction,
    Frequency,
    LifeEventStatus,
    Relationship,
)


# ── Shared / nested ──────────────────────────────────────────────────────────


class KeyDateIn(BaseModel):
    date: date
    label: str = Field(min_length=1, max_length=160)


class KeyDateOut(KeyDateIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


class InteractionIn(BaseModel):
    occurred_at: datetime | None = None
    channel: Channel = Channel.message
    direction: Direction = Direction.outbound
    sentiment: float = Field(default=0.0, ge=-1.0, le=1.0)
    summary: str | None = None


class InteractionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    contact_id: int
    occurred_at: datetime
    channel: Channel
    direction: Direction
    sentiment: float
    summary: str | None


class LifeEventIn(BaseModel):
    event_type: str = Field(max_length=80)
    title: str = Field(max_length=240)
    description: str | None = None
    event_date: date | None = None
    source: str = "manual"


class LifeEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    contact_id: int
    event_type: str
    title: str
    description: str | None
    event_date: date | None
    source: str
    status: LifeEventStatus
    suggested_message: str | None
    created_at: datetime


class LifeEventUpdate(BaseModel):
    status: LifeEventStatus | None = None
    suggested_message: str | None = None


class SocialSnapshotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    contact_id: int
    platform: str
    url: str
    title: str | None
    raw_text: str | None
    fetched_at: datetime


# ── Contact ──────────────────────────────────────────────────────────────────


class ContactBase(BaseModel):
    first_name: str = Field(min_length=1, max_length=120)
    last_name: str | None = Field(default=None, max_length=120)
    relationship_type: Relationship = Relationship.acquaintance
    contact_frequency: Frequency = Frequency.monthly
    company: str | None = None
    position: str | None = None
    location: str | None = None
    birth_date: date | None = None
    email: EmailStr | None = None
    phone: str | None = None
    whatsapp: str | None = None
    telegram: str | None = None
    viber: str | None = None
    instagram_url: str | None = None
    facebook_url: str | None = None
    linkedin_url: str | None = None
    twitter_url: str | None = None
    youtube_url: str | None = None
    github_url: str | None = None
    website_url: str | None = None
    notes: str | None = None


class ContactCreate(ContactBase):
    tags: list[str] = Field(default_factory=list)
    key_dates: list[KeyDateIn] = Field(default_factory=list)


class ContactUpdate(BaseModel):
    first_name: str | None = Field(default=None, min_length=1, max_length=120)
    last_name: str | None = None
    relationship_type: Relationship | None = None
    contact_frequency: Frequency | None = None
    company: str | None = None
    position: str | None = None
    location: str | None = None
    birth_date: date | None = None
    email: EmailStr | None = None
    phone: str | None = None
    whatsapp: str | None = None
    telegram: str | None = None
    viber: str | None = None
    instagram_url: str | None = None
    facebook_url: str | None = None
    linkedin_url: str | None = None
    twitter_url: str | None = None
    youtube_url: str | None = None
    github_url: str | None = None
    website_url: str | None = None
    notes: str | None = None
    tags: list[str] | None = None


class ContactSummary(BaseModel):
    """Lightweight view for lists and the dashboard."""

    model_config = ConfigDict(from_attributes=True)
    id: int
    first_name: str
    last_name: str | None
    full_name: str
    relationship_type: Relationship
    contact_frequency: Frequency
    company: str | None
    position: str | None
    warmth_score: float
    warmth_status: str
    last_contacted_at: datetime | None
    tags: list[str] = Field(default_factory=list)

    @classmethod
    def from_model(cls, c) -> "ContactSummary":
        return cls(
            id=c.id,
            first_name=c.first_name,
            last_name=c.last_name,
            full_name=c.full_name,
            relationship_type=c.relationship_type,
            contact_frequency=c.contact_frequency,
            company=c.company,
            position=c.position,
            warmth_score=c.warmth_score,
            warmth_status=c.warmth_status,
            last_contacted_at=c.last_contacted_at,
            tags=[t.name for t in c.tags],
        )


class ContactDetail(ContactBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    full_name: str
    created_at: datetime
    updated_at: datetime
    warmth_score: float
    warmth_status: str
    last_contacted_at: datetime | None
    ai_dossier: str | None
    ai_dossier_updated_at: datetime | None
    tags: list[str] = Field(default_factory=list)
    key_dates: list[KeyDateOut] = Field(default_factory=list)
    interactions: list[InteractionOut] = Field(default_factory=list)
    life_events: list[LifeEventOut] = Field(default_factory=list)
    social_snapshots: list[SocialSnapshotOut] = Field(default_factory=list)
    days_since_contact: int = 0
    is_due: bool = False

    @classmethod
    def from_model(cls, c) -> "ContactDetail":
        from . import warmth

        data = {
            field: getattr(c, field)
            for field in ContactBase.model_fields
        }
        return cls(
            **data,
            id=c.id,
            full_name=c.full_name,
            created_at=c.created_at,
            updated_at=c.updated_at,
            warmth_score=c.warmth_score,
            warmth_status=c.warmth_status,
            last_contacted_at=c.last_contacted_at,
            ai_dossier=c.ai_dossier,
            ai_dossier_updated_at=c.ai_dossier_updated_at,
            tags=[t.name for t in c.tags],
            key_dates=[KeyDateOut.model_validate(k) for k in c.key_dates],
            interactions=[InteractionOut.model_validate(i) for i in c.interactions],
            life_events=[LifeEventOut.model_validate(e) for e in c.life_events],
            social_snapshots=[
                SocialSnapshotOut.model_validate(s) for s in c.social_snapshots
            ],
            days_since_contact=round(warmth.days_since_last_contact(c)),
            is_due=warmth.is_due(c),
        )


# ── AI & import payloads ─────────────────────────────────────────────────────


class OutreachRecommendation(BaseModel):
    should_contact: bool
    urgency: str
    channel: str
    timing: str
    reason: str
    talking_points: list[str]
    draft_message: str
    source: str = "ai"


class ImportRequest(BaseModel):
    url: str
    analyze: bool = True


class ImportResult(BaseModel):
    snapshot: SocialSnapshotOut
    detected_events: list[LifeEventOut] = Field(default_factory=list)


# ── Dashboard ────────────────────────────────────────────────────────────────


class SuggestedContact(BaseModel):
    contact: ContactSummary
    reason: str
    days_overdue: int
    days_since_contact: int


class UpcomingDate(BaseModel):
    contact: ContactSummary
    label: str
    date: date
    days_away: int


class DashboardStats(BaseModel):
    total_contacts: int
    due_now: int
    average_warmth: float
    hot: int
    warm: int
    cooling: int
    cold: int
    pending_life_events: int


class Dashboard(BaseModel):
    stats: DashboardStats
    suggestions: list[SuggestedContact]
    upcoming: list[UpcomingDate]
    pending_events: list[LifeEventOut]
    ai_enabled: bool
