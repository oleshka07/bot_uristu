"""Aggregator shim: the daily job now lives in the automation module.

Kept so existing ``from . import daily`` / ``app.run_daily`` call sites keep
working unchanged.
"""

from __future__ import annotations

from app.modules.automation.daily import build_digest_html, run_daily_job

__all__ = ["build_digest_html", "run_daily_job"]
