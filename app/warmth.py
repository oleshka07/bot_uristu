"""Aggregator shim: the warmth engine now lives in the interactions module.

Kept so existing ``from app import warmth`` / ``from . import warmth`` call
sites (services, dashboard, connectors, tests) keep working unchanged.
"""

from __future__ import annotations

from app.modules.interactions.warmth import (
    FREQUENCY_DAYS,
    compute_warmth,
    days_since_last_contact,
    is_due,
    overdue_ratio,
    refresh,
    status_for_score,
    target_days,
)

__all__ = [
    "FREQUENCY_DAYS",
    "target_days",
    "days_since_last_contact",
    "status_for_score",
    "compute_warmth",
    "is_due",
    "overdue_ratio",
    "refresh",
]
