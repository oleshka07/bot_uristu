"""Aggregator shim: the AI engine now lives in the insights module.

Kept so existing ``from . import ai`` / ``ai.<fn>()`` call sites (routers,
connectors) keep working unchanged.
"""

from __future__ import annotations

from app.modules.insights.ai import (
    detect_life_events,
    generate_dossier,
    recommend_outreach,
    score_sentiments,
    suggest_event_message,
)

__all__ = [
    "generate_dossier",
    "recommend_outreach",
    "score_sentiments",
    "suggest_event_message",
    "detect_life_events",
]
