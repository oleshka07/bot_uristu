"""Compatibility shim — moved to app.core.diagnostics."""
from app.core.diagnostics import (  # noqa: F401
    RingBufferHandler,
    install,
    recent,
    snapshot,
)
