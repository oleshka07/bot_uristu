"""The daily job: refresh warmth, sync Google, and send a digest.

Runs on a schedule (see scheduler.py) and can be triggered manually via the
API. Keeps everything in one place so it's easy to reason about.
"""

from __future__ import annotations

import logging

from app import crud, dashboard

from . import telegram
from app.core.config import settings
from app.core.database import SessionLocal
from app.integrations import chater, google

logger = logging.getLogger("networking.daily")


def build_digest_html(data) -> str:
    s = data.stats

    def row(title, items):
        if not items:
            return f"<p style='color:#888'>{title}: nothing.</p>"
        lis = "".join(items)
        return (
            f"<h3 style='margin:18px 0 6px'>{title}</h3>"
            f"<ul style='margin:0;padding-left:18px'>{lis}</ul>"
        )

    suggestions = [
        f"<li><b>{sg.contact.full_name}</b> — {sg.reason}</li>"
        for sg in data.suggestions
    ]
    upcoming = [
        f"<li><b>{u.contact.full_name}</b> — {u.label} "
        f"({'today' if u.days_away == 0 else f'in {u.days_away}d'})</li>"
        for u in data.upcoming
    ]
    events = [
        f"<li><b>{e.title}</b> — {e.event_type}</li>" for e in data.pending_events
    ]

    return f"""\
<div style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;max-width:560px;
            margin:0 auto;color:#1a1a1a">
  <h2 style="margin-bottom:4px">Your networking digest</h2>
  <p style="color:#666;margin-top:0">
    {s.total_contacts} contacts · {s.due_now} due now · avg warmth {s.average_warmth}
  </p>
  {row("Reach out today", suggestions)}
  {row("Upcoming dates", upcoming)}
  {row("New life events", events)}
  <p style="color:#aaa;font-size:12px;margin-top:24px">
    Sent by your Networking AI service.
  </p>
</div>"""


def run_daily_job(send_digest: bool = True) -> dict:
    """Returns a summary dict describing what happened."""
    db = SessionLocal()
    summary: dict = {"warmth_refreshed": 0, "sync": None, "digest_sent": False}
    try:
        summary["warmth_refreshed"] = crud.refresh_all_warmth(db)

        # Self-healing: clean up any duplicate Chater-imported contacts.
        try:
            summary["duplicates_removed"] = chater.dedupe(db)
        except Exception as exc:  # pragma: no cover
            logger.warning("daily dedupe failed: %s", exc)

        g_status = google.status(db)
        if g_status["connected"]:
            report = google.sync(db)
            summary["sync"] = report.as_dict()

        data = dashboard.build_dashboard(db)
        summary["due_now"] = data.stats.due_now

        if send_digest:
            # Email digest (via Gmail, if connected).
            recipient = settings.digest_email_to or (
                g_status.get("account_email") if g_status["connected"] else None
            )
            if recipient and g_status["connected"]:
                html = build_digest_html(data)
                summary["digest_sent"] = google.send_email(
                    db, recipient, "Your networking digest", html
                )
                summary["digest_to"] = recipient
            else:
                summary["digest_skipped"] = (
                    "No recipient or Google not connected (needed to send mail)."
                )
            # Telegram digest (independent of email).
            if settings.telegram_configured and settings.telegram_chat_id:
                summary["telegram_sent"] = telegram.send_message(
                    telegram.digest_text(data)
                )
        logger.info("Daily job finished: %s", summary)
    finally:
        db.close()
    return summary
