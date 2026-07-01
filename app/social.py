"""Aggregator shim: social connectors now live in the integrations module.

Kept so existing ``from app import social`` / ``social.fetch_snapshot`` call
sites (the import router) keep working unchanged.
"""

from __future__ import annotations

from app.modules.integrations.social.connector import (
    PLATFORM_HOSTS,
    SnapshotData,
    detect_platform,
    fetch_generic,
    fetch_snapshot,
    fetch_with_scraper,
    register_connector,
)

__all__ = [
    "SnapshotData",
    "PLATFORM_HOSTS",
    "detect_platform",
    "fetch_generic",
    "fetch_snapshot",
    "fetch_with_scraper",
    "register_connector",
]
