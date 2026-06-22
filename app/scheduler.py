"""Background scheduler for the daily job.

Enabled with SCHEDULER_ENABLED=true. Uses APScheduler's BackgroundScheduler,
which runs in a daemon thread inside the web process — fine for a single-user
internal tool. For multi-process deployments, run the daily job from a cron /
systemd timer calling `python -m app.run_daily` instead.
"""

from __future__ import annotations

import logging

from .config import settings
from .daily import run_daily_job

logger = logging.getLogger("networking.scheduler")

_scheduler = None


def start() -> None:
    global _scheduler
    if not settings.scheduler_enabled:
        logger.info("Scheduler disabled (SCHEDULER_ENABLED is false).")
        return
    if _scheduler is not None:
        return
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger
    except Exception as exc:  # pragma: no cover
        logger.warning("APScheduler unavailable: %s", exc)
        return

    _scheduler = BackgroundScheduler(daemon=True)
    _scheduler.add_job(
        run_daily_job,
        CronTrigger(hour=settings.daily_run_hour, minute=0),
        id="daily_job",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    _scheduler.start()
    logger.info(
        "Scheduler started; daily job at %02d:00 server time.",
        settings.daily_run_hour,
    )


def shutdown() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
