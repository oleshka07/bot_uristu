"""Aggregator shim: the Chater importer now lives in the integrations module.

Kept so existing ``from app.integrations import chater`` call sites (the
integrations router, the daily job, and a test) keep working unchanged.
"""

from __future__ import annotations

from app.modules.integrations.chater.importer import (
    ImportReport,
    dedupe,
    duplicate_count,
    import_data,
    inspect,
    status,
)

__all__ = [
    "ImportReport",
    "status",
    "inspect",
    "import_data",
    "duplicate_count",
    "dedupe",
]
