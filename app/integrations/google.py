"""Aggregator shim: the Google client now lives in the integrations module.

Kept so existing ``from app.integrations import google`` call sites (the
integrations router and the daily job) keep working unchanged.
"""

from __future__ import annotations

from app.modules.integrations.google.client import (
    SyncReport,
    build_authorization_url,
    disconnect,
    handle_oauth_callback,
    send_email,
    status,
    sync,
)

__all__ = [
    "SyncReport",
    "disconnect",
    "status",
    "build_authorization_url",
    "handle_oauth_callback",
    "sync",
    "send_email",
]
