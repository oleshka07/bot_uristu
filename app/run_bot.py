"""Run the Telegram bot (long polling, incl. Business proxy). Own process:

    python -m app.run_bot
"""

from __future__ import annotations

import logging

from .core.database import init_db
from .modules.telegram_bot.poller import run

logging.basicConfig(level=logging.INFO)
# httpx logs every request URL at INFO — for the Bot API that URL contains
# the bot token. Keep it quiet so the token never lands in logs.
logging.getLogger("httpx").setLevel(logging.WARNING)

if __name__ == "__main__":
    init_db()
    run()
