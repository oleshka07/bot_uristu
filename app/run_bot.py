"""Run the Telegram command bot (long polling). Use as its own process:

    python -m app.run_bot
"""

from __future__ import annotations

import logging

from .database import init_db
from .telegram import run_polling

logging.basicConfig(level=logging.INFO)

if __name__ == "__main__":
    init_db()
    run_polling()
