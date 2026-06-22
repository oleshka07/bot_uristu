"""Run the daily job once and exit. For cron / systemd timers:

    python -m app.run_daily
"""

from __future__ import annotations

import json

from .daily import run_daily_job
from .database import init_db

if __name__ == "__main__":
    init_db()
    print(json.dumps(run_daily_job(), indent=2, default=str))
