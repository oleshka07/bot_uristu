"""Telegram update dispatcher: admin commands, Business proxy, callbacks.

All admin-facing text is HTML. Every handler is defensive — an exception in
one update must never kill the polling loop (the poller catches too, but we
keep failures local so one bad update doesn't block the batch).
"""

from __future__ import annotations

import html
import logging

from app.core.config import settings
from app.core.database import SessionLocal
from app.modules.contacts.models import Contact

from . import service
from .models import DraftStatus
from .transcribe import transcribe_ogg

logger = logging.getLogger("networking.tgbot")


def _esc(s: str | None) -> str:
    return html.escape(s or "")


def _admin_id() -> int | None:
    try:
        return int(settings.telegram_chat_id) if settings.telegram_chat_id else None
    except (TypeError, ValueError):
        return None


# ── Preview rendering ────────────────────────────────────────────────────────


def _draft_keyboard(draft_id: int, has_draft: bool) -> dict:
    row = []
    if has_draft:
        row.append({"text": "✅ Надіслати", "callback_data": f"d:s:{draft_id}"})
    row.append({"text": "✋ Вручну", "callback_data": f"d:m:{draft_id}"})
    row.append({"text": "⏭ Пропустити", "callback_data": f"d:k:{draft_id}"})
    return {"inline_keyboard": [row]}


def _preview_text(contact, draft, is_new: bool) -> str:
    head = f"👤 <b>{_esc(contact.full_name)}</b>"
    if contact.telegram:
        head += f" ({_esc(contact.telegram)})"
    if is_new:
        head += " · 🆕 новий контакт"
    else:
        head += (
            f" · {_esc(contact.relationship_type.value)}"
            f" · {_esc(contact.warmth_status)} {round(contact.warmth_score)}"
        )
    body = f"\n\n💬 {_esc(draft.incoming_text)}"
    if draft.draft_text.strip():
        body += f"\n\n✍️ <b>Чернетка:</b>\n{_esc(draft.draft_text)}"
        body += "\n\n<i>Reply текстом/голосом — скоригую чернетку.</i>"
    else:
        body += "\n\n<i>Чернетки немає (AI недоступний) — відповідай вручну.</i>"
    return head + body


# ── Update handlers ──────────────────────────────────────────────────────────


def handle_business_connection(client, bc: dict) -> None:
    with SessionLocal() as db:
        service.upsert_connection(
            db,
            connection_id=bc.get("id", ""),
            user_chat_id=(bc.get("user") or {}).get("id"),
            is_enabled=bool(bc.get("is_enabled", True)),
        )
    logger.info("Business connection updated: %s", bc.get("id"))


def handle_business_message(client, msg: dict) -> None:
    admin = _admin_id()
    chat = msg.get("chat") or {}
    sender = msg.get("from") or {}
    bc_id = msg.get("business_connection_id")
    chat_id = chat.get("id")
    if chat_id is None:
        return

    text = msg.get("text") or msg.get("caption") or ""
    if not text and msg.get("voice"):
        audio = client.download_file(msg["voice"].get("file_id", ""))
        transcript = transcribe_ogg(audio) if audio else None
        text = f"[голосове] {transcript}" if transcript else "[голосове повідомлення]"
    if not text:
        return  # stickers/photos without caption — nothing to draft on

    # The user's own messages (typed on their phone) also arrive here —
    # log them as outgoing history, never draft a reply to yourself.
    if sender.get("id") is not None and sender.get("id") != chat_id:
        with SessionLocal() as db:
            contact, _ = service.find_or_create_contact(
                db,
                chat_id,
                chat.get("first_name") or "Unknown",
                chat.get("last_name"),
                chat.get("username"),
            )
            from datetime import datetime, timezone

            from app import warmth
            from app.modules.interactions import service as itx
            from app.modules.interactions.models import Channel, Direction

            ext = f"tgb:{chat_id}:{msg.get('message_id')}"
            if not itx.interaction_exists(db, contact.id, ext):
                itx.add_synced_interaction(
                    db,
                    contact,
                    occurred_at=datetime.now(timezone.utc),
                    channel=Channel.message,
                    direction=Direction.outbound,
                    summary=text[:300],
                    source="telegram",
                    external_id=ext,
                )
                db.refresh(contact)
                warmth.refresh(contact)
                db.commit()
        return

    with SessionLocal() as db:
        draft, contact, is_new = service.handle_incoming(
            db,
            chat_id=chat_id,
            text=text,
            message_id=msg.get("message_id") or 0,
            first_name=sender.get("first_name") or chat.get("first_name") or "Unknown",
            last_name=sender.get("last_name") or chat.get("last_name"),
            username=sender.get("username") or chat.get("username"),
            business_connection_id=bc_id,
        )
        if admin:
            sent = client.send_message(
                admin,
                _preview_text(contact, draft, is_new),
                reply_markup=_draft_keyboard(draft.id, bool(draft.draft_text.strip())),
            )
            if sent:
                service.set_admin_message(db, draft, sent.get("message_id", 0))


def handle_callback(client, cb: dict) -> None:
    data = cb.get("data") or ""
    cb_id = cb.get("id", "")
    msg = cb.get("message") or {}
    if not data.startswith("d:"):
        client.answer_callback(cb_id)
        return
    try:
        _, action, raw_id = data.split(":", 2)
        draft_id = int(raw_id)
    except ValueError:
        client.answer_callback(cb_id)
        return

    with SessionLocal() as db:
        draft = service.get_draft(db, draft_id)
        if draft is None or draft.status != DraftStatus.pending:
            client.answer_callback(cb_id, "Уже неактуально")
            return

        if action == "s":
            ok = service.approve_and_send(db, client, draft)
            client.answer_callback(cb_id, "Надіслано ✅" if ok else "Помилка надсилання")
            if ok and msg:
                client.edit_message_text(
                    msg["chat"]["id"],
                    msg["message_id"],
                    (msg.get("text") or "") + "\n\n✅ <b>Надіслано</b>",
                )
        elif action == "m":
            service.mark(db, draft, DraftStatus.manual)
            client.answer_callback(cb_id, "Ок, відповідай сам")
            if msg:
                client.edit_message_text(
                    msg["chat"]["id"],
                    msg["message_id"],
                    (msg.get("text") or "") + "\n\n✋ <b>Вручну</b>",
                )
        elif action == "k":
            service.mark(db, draft, DraftStatus.skipped)
            client.answer_callback(cb_id, "Пропущено")
            if msg:
                client.edit_message_text(
                    msg["chat"]["id"],
                    msg["message_id"],
                    (msg.get("text") or "") + "\n\n⏭ <b>Пропущено</b>",
                )
        else:
            client.answer_callback(cb_id)


def handle_admin_message(client, msg: dict) -> None:
    """Messages in the admin's own chat with the bot: commands, or a reply
    to a draft preview (text/voice) that reformulates the draft."""
    admin = _admin_id()
    chat_id = (msg.get("chat") or {}).get("id")
    if admin is None or chat_id != admin:
        # Someone else talking to the bot directly — ignore politely.
        return

    reply_to = (msg.get("reply_to_message") or {}).get("message_id")
    text = msg.get("text") or ""

    # Reply to a preview → reformulate that draft.
    if reply_to:
        instruction = text
        if not instruction and msg.get("voice"):
            audio = client.download_file(msg["voice"].get("file_id", ""))
            instruction = transcribe_ogg(audio) if audio else None
            if not instruction:
                client.send_message(
                    admin,
                    "Не зміг розшифрувати голосове (потрібен OPENAI_API_KEY "
                    "або GEMINI_API_KEY).",
                )
                return
        if not instruction:
            return
        with SessionLocal() as db:
            draft = service.find_pending_by_admin_message(db, reply_to)
            if draft is None:
                return
            new_text = service.reformulate(db, draft, instruction)
            if new_text is None:
                client.send_message(admin, "Не вдалося переписати чернетку.")
                return
            contact = db.get(Contact, draft.contact_id)
            edited = client.edit_message_text(
                admin,
                reply_to,
                _preview_text(contact, draft, False),
                reply_markup=_draft_keyboard(draft.id, True),
            )
            if not edited:
                sent = client.send_message(
                    admin,
                    _preview_text(contact, draft, False),
                    reply_markup=_draft_keyboard(draft.id, True),
                )
                if sent:
                    service.set_admin_message(db, draft, sent.get("message_id", 0))
        return

    if text.startswith("/"):
        _handle_command(client, admin, text)


def _handle_command(client, admin: int, text: str) -> None:
    from app import crud, dashboard, warmth
    from app.modules.automation import telegram as tg

    cmd, _, arg = text.strip().partition(" ")
    cmd = cmd.lower().lstrip("/").split("@")[0]

    with SessionLocal() as db:
        if cmd in ("start", "help"):
            client.send_message(
                admin,
                "<b>Networking AI</b>\n"
                "/today — кому написати сьогодні\n"
                "/due — всі прострочені\n"
                "/find &lt;ім'я&gt; — пошук контакту\n\n"
                "Вхідні з Telegram Business приходять сюди з чернеткою "
                "відповіді: ✅ надіслати · reply — скоригувати.",
            )
        elif cmd in ("today", "network", "digest"):
            client.send_message(admin, tg.digest_text(dashboard.build_dashboard(db)))
        elif cmd == "due":
            contacts = [c for c in crud.list_contacts(db, sort="due") if warmth.is_due(c)]
            if not contacts:
                client.send_message(admin, "Ніхто не прострочений ✦")
                return
            lines = ["<b>Прострочені</b>"]
            for c in contacts[:20]:
                d = round(warmth.days_since_last_contact(c))
                lines.append(f"• {_esc(c.full_name)} — {d}д ({c.warmth_status})")
            client.send_message(admin, "\n".join(lines))
        elif cmd == "find":
            if not arg.strip():
                client.send_message(admin, "Використання: /find &lt;ім'я чи компанія&gt;")
                return
            results = crud.list_contacts(db, search=arg.strip(), sort="name")
            if not results:
                client.send_message(admin, f"Нічого не знайшов за «{_esc(arg)}».")
                return
            lines = [f"<b>Збіги за «{_esc(arg)}»</b>"]
            for c in results[:15]:
                sub = " · ".join(filter(None, [c.position, c.company]))
                lines.append(
                    f"• {_esc(c.full_name)}"
                    + (f" — {_esc(sub)}" if sub else "")
                    + f" ({c.warmth_status} {round(c.warmth_score)})"
                )
            client.send_message(admin, "\n".join(lines))
        else:
            client.send_message(admin, "Невідома команда. Спробуй /help.")


# ── Entry point ──────────────────────────────────────────────────────────────


def dispatch(client, update: dict) -> None:
    try:
        if "business_connection" in update:
            handle_business_connection(client, update["business_connection"])
        elif "business_message" in update:
            handle_business_message(client, update["business_message"])
        elif "callback_query" in update:
            handle_callback(client, update["callback_query"])
        elif "message" in update or "edited_message" in update:
            handle_admin_message(
                client, update.get("message") or update.get("edited_message")
            )
    except Exception as exc:  # pragma: no cover - resilience
        logger.exception("Update %s failed: %s", update.get("update_id"), exc)
