"""Воркер фонового AI (Claude Code на підписці). Окремий процес:

    python -m app.run_worker
"""

from __future__ import annotations

import logging

from .core.database import init_db
from .modules.aijobs.worker import run_forever

logging.basicConfig(level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)

if __name__ == "__main__":
    init_db()
    run_forever()
