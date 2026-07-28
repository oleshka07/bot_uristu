"""Telegram delivery + a lightweight command bot for Networking AI.

Two roles:
  * send_message() — push the daily digest / alerts to your Telegram.
  * a long-polling command bot (run via `python -m app.run_bot`) answering
    /today, /due, /find — a quick read-only window into your network.

Uses the Bot API directly over HTTPS (no extra dependency). This is separate
from the existing Chater bot; give it its own bot token from @BotFather.
"""

from __future__ import annotations

import html
import logging
import time

import httpx

from app.core.config import settings

logger = logging.getLogger("networking.telegram")

API = "https://api.telegram.org/bot{token}/{method}"


def _call(method: str, **payload):
    token = settings.telegram_bot_token
    if not token:
        return None
    try:
        with httpx.Client(timeout=35.0) as client:
            resp = client.post(API.format(token=token, method=method), json=payload)
            data = resp.json()
            if not data.get("ok"):
                logger.warning("Telegram %s error: %s", method, data.get("description"))
            return data
    except Exception as exc:  # pragma: no cover
        logger.warning("Telegram %s failed: %s", method, exc)
        return None


def send_message(
    text: str, chat_id: str | None = None, reply_markup: dict | None = None
) -> bool:
    chat = chat_id or settings.telegram_chat_id
    if not (settings.telegram_bot_token and chat):
        return False
    payload = dict(
        chat_id=chat,
        text=text,
        parse_mode="HTML",
        disable_web_page_preview=True,
    )
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
    data = _call("sendMessage", **payload)
    return bool(data and data.get("ok"))


def send_and_get_id(text: str, chat_id: str | None = None) -> tuple[str, int] | None:
    """Як send_message, але повертає (chat_id, message_id) — щоб потім видалити."""
    chat = chat_id or settings.telegram_chat_id
    if not (settings.telegram_bot_token and chat):
        return None
    data = _call("sendMessage", chat_id=chat, text=text, parse_mode="HTML",
                 disable_web_page_preview=True)
    if not (data and data.get("ok")):
        return None
    return str(chat), int(data["result"]["message_id"])


def delete_message(chat_id: str, message_id: int) -> bool:
    data = _call("deleteMessage", chat_id=chat_id, message_id=message_id)
    return bool(data and data.get("ok"))


# ── Digest text (Telegram-friendly, HTML) ────────────────────────────────────


def digest_text(data) -> str:
    s = data.stats
    lines = [
        "<b>📇 Networking digest</b>",
        f"{s.total_contacts} contacts · {s.due_now} due · avg warmth {s.average_warmth}",
        "",
    ]
    if data.suggestions:
        lines.append("<b>Reach out today</b>")
        for sg in data.suggestions:
            lines.append(f"• {html.escape(sg.contact.full_name)} — {html.escape(sg.reason)}")
        lines.append("")
    if data.upcoming:
        lines.append("<b>Upcoming</b>")
        for u in data.upcoming:
            when = "today" if u.days_away == 0 else f"in {u.days_away}d"
            lines.append(f"• {html.escape(u.contact.full_name)} — {html.escape(u.label)} ({when})")
        lines.append("")
    if data.pending_events:
        lines.append("<b>New life events</b>")
        for e in data.pending_events:
            lines.append(f"• {html.escape(e.title)}")
    return "\n".join(lines).strip()


# ── Command bot (long polling) ───────────────────────────────────────────────


def _handle_command(text: str) -> str:
    from app import dashboard, warmth
    from app.core.database import SessionLocal

    cmd, _, arg = text.strip().partition(" ")
    cmd = cmd.lower().lstrip("/").split("@")[0]
    db = SessionLocal()
    try:
        if cmd in ("start", "help"):
            return (
                "<b>Networking AI</b>\n"
                "/today — who to contact today\n"
                "/due — everyone overdue\n"
                "/find &lt;name&gt; — search a contact"
            )
        if cmd == "today":
            return digest_text(dashboard.build_dashboard(db))
        if cmd == "due":
            from app import crud

            contacts = [c for c in crud.list_contacts(db, sort="due") if warmth.is_due(c)]
            if not contacts:
                return "Nobody is overdue. ✦"
            lines = ["<b>Overdue</b>"]
            for c in contacts[:20]:
                d = round(warmth.days_since_last_contact(c))
                lines.append(f"• {html.escape(c.full_name)} — {d}d ({c.warmth_status})")
            return "\n".join(lines)
        if cmd == "find":
            from app import crud

            if not arg.strip():
                return "Usage: /find &lt;name or company&gt;"
            results = crud.list_contacts(db, search=arg.strip(), sort="name")
            if not results:
                return f"No contacts match “{html.escape(arg)}”."
            lines = [f"<b>Matches for “{html.escape(arg)}”</b>"]
            for c in results[:15]:
                sub = " · ".join(filter(None, [c.position, c.company]))
                lines.append(
                    f"• {html.escape(c.full_name)}"
                    + (f" — {html.escape(sub)}" if sub else "")
                    + f" ({c.warmth_status} {round(c.warmth_score)})"
                )
            return "\n".join(lines)
        return "Unknown command. Try /help."
    finally:
        db.close()


def run_polling() -> None:
    if not settings.telegram_polling_enabled:
        logger.warning(
            "TELEGRAM_POLLING_ENABLED is false — not polling. In the single-bot "
            "setup, Chater serves commands and pulls /api/digest/text. Set the "
            "flag only if running a SEPARATE Networking AI bot with its own token."
        )
        while True:
            time.sleep(3600)
    if not settings.telegram_bot_token:
        logger.warning("TELEGRAM_BOT_TOKEN not set; bot idle. Set it and restart.")
        while True:  # stay alive so the container doesn't restart-loop
            time.sleep(3600)
    logger.info("Telegram command bot started (long polling).")
    offset = None
    while True:
        try:
            data = _call("getUpdates", offset=offset, timeout=30)
            if not data or not data.get("ok"):
                time.sleep(3)
                continue
            for update in data["result"]:
                offset = update["update_id"] + 1
                message = update.get("message") or update.get("edited_message")
                if not message:
                    continue
                chat_id = str(message["chat"]["id"])
                txt = message.get("text", "")
                if not txt.startswith("/"):
                    continue
                reply = _handle_command(txt)
                send_message(reply, chat_id=chat_id)
        except Exception as exc:  # pragma: no cover
            logger.warning("Polling loop error: %s", exc)
            time.sleep(5)
