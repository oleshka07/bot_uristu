"""Aggregator shim: re-exports every API schema from its owning module.

The real schemas now live in ``app/modules/*/schemas.py`` (one file per domain).
This module keeps the flat ``from app.schemas import X`` import path working for
routers, services and tests until the final cleanup step of the refactor.
"""

from __future__ import annotations

from app.modules.contacts.schemas import (
    ContactBase,
    ContactCreate,
    ContactDetail,
    ContactSummary,
    ContactUpdate,
    KeyDateIn,
    KeyDateOut,
)
from app.modules.dashboard.schemas import (
    Dashboard,
    DashboardStats,
    SuggestedContact,
    UpcomingDate,
)
from app.modules.insights.schemas import (
    LifeEventIn,
    LifeEventOut,
    LifeEventUpdate,
    OutreachRecommendation,
)
from app.modules.integrations.social.schemas import (
    ImportRequest,
    ImportResult,
    SocialSnapshotOut,
)
from app.modules.interactions.schemas import InteractionIn, InteractionOut

__all__ = [
    "KeyDateIn",
    "KeyDateOut",
    "InteractionIn",
    "InteractionOut",
    "LifeEventIn",
    "LifeEventOut",
    "LifeEventUpdate",
    "OutreachRecommendation",
    "SocialSnapshotOut",
    "ImportRequest",
    "ImportResult",
    "ContactBase",
    "ContactCreate",
    "ContactUpdate",
    "ContactSummary",
    "ContactDetail",
    "SuggestedContact",
    "UpcomingDate",
    "DashboardStats",
    "Dashboard",
]
