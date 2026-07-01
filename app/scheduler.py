"""Aggregator shim: the scheduler now lives in the automation module.

Kept so existing ``from . import scheduler`` call sites keep working.
"""

from __future__ import annotations

from app.modules.automation.scheduler import shutdown, start

__all__ = ["start", "shutdown"]
