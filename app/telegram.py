"""Aggregator shim: Telegram delivery + command bot now live in the
automation module.

Kept so existing ``from . import telegram`` / ``app.run_bot`` call sites keep
working unchanged.
"""

from __future__ import annotations

from app.modules.automation.telegram import (
    digest_text,
    run_polling,
    send_message,
)

__all__ = ["send_message", "digest_text", "run_polling"]
