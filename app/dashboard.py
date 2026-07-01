"""Aggregator shim: dashboard aggregation now lives in the dashboard module.

Kept so existing ``from app import dashboard`` / ``from . import dashboard``
call sites (router, daily job, telegram digest) keep working unchanged.
"""

from __future__ import annotations

from app.modules.dashboard.service import build_dashboard

__all__ = ["build_dashboard"]
