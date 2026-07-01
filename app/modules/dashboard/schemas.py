"""Dashboard API schemas — aggregates contacts + insights into the daily view."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel

from app.modules.contacts.schemas import ContactSummary
from app.modules.insights.schemas import LifeEventOut


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
