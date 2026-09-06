"""Contact API schemas, including the aggregated ContactDetail read-model."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.modules.insights.schemas import ContactFactOut, LifeEventOut
from app.modules.integrations.social.schemas import SocialSnapshotOut
from app.modules.interactions.schemas import InteractionOut

from .models import Frequency, Relationship


class KeyDateIn(BaseModel):
    date: date
    label: str = Field(min_length=1, max_length=160)


class KeyDateOut(KeyDateIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


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
    tone: str | None = Field(default=None, max_length=80)
    do_not_contact: bool = False
    importance: int = Field(default=0, ge=0, le=3)


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
    tone: str | None = Field(default=None, max_length=80)
    do_not_contact: bool | None = None
    importance: int | None = Field(default=None, ge=0, le=3)
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
    telegram_chat_id: int | None = None
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
    facts: list[ContactFactOut] = Field(default_factory=list)
    goals: list[dict] = Field(default_factory=list)
    days_since_contact: int = 0
    is_due: bool = False

    @classmethod
    def from_model(cls, c) -> "ContactDetail":
        from app import warmth

        data = {field: getattr(c, field) for field in ContactBase.model_fields}
        return cls(
            **data,
            id=c.id,
            full_name=c.full_name,
            telegram_chat_id=c.telegram_chat_id,
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
            facts=[
                ContactFactOut.model_validate(f)
                for f in c.facts
                if f.is_current
            ],
            goals=[
                {"id": g.id, "title": g.title, "status": g.status}
                for g in getattr(c, "goals", [])
            ],
            days_since_contact=round(warmth.days_since_last_contact(c)),
            is_due=warmth.is_due(c),
        )
