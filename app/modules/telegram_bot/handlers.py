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


# Reply-keyboard buttons the old Chater bot left stuck in the chat. Tapping
# one used to open Chater's planner — now we clear the keyboard and help.
_LEGACY_BUTTONS = {
    "задачі", "огляд", "промпти", "налаштування", "меню",
    "📋 задачі", "📊 огляд", "📝 промпти", "⚙️ налаштування", "☰ меню",
}
_REMOVE_KEYBOARD = {"remove_keyboard": True}


def _is_legacy_button(text: str) -> bool:
    return text.strip().casefold() in _LEGACY_BUTTONS


def _admin_id() -> int | None:
    try:
        return int(settings.telegram_chat_id) if settings.telegram_chat_id else None
    except (TypeError, ValueError):
        return None


# ── Preview rendering ────────────────────────────────────────────────────────


def _draft_keyboard(draft_id: int, has_draft: bool, outreach: bool = False) -> dict:
    row1 = []
    if has_draft:
        row1.append({"text": "✅ Надіслати", "callback_data": f"d:s:{draft_id}"})
    row1.append({"text": "✋ Вручну", "callback_data": f"d:m:{draft_id}"})
    row1.append({"text": "⏭ Пропустити", "callback_data": f"d:k:{draft_id}"})
    row2 = []
    if has_draft:
        row2.append({"text": "🌐 Переклад", "callback_data": f"d:t:{draft_id}"})
    row2.append({"text": "📇 Контакти", "callback_data": f"d:c:{draft_id}"})
    if outreach:
        row2.append({"text": "🚫 Стоп-лист", "callback_data": f"d:x:{draft_id}"})
    return {"inline_keyboard": [row1, row2] if row2 else [row1]}


def _translate_keyboard(draft_id: int) -> dict:
    return {
        "inline_keyboard": [
            [
                {"text": "🇬🇧 EN", "callback_data": f"d:t:{draft_id}:en"},
                {"text": "🇨🇿 CS", "callback_data": f"d:t:{draft_id}:cs"},
                {"text": "🇷🇺 RU", "callback_data": f"d:t:{draft_id}:ru"},
                {"text": "🇺🇦 UK", "callback_data": f"d:t:{draft_id}:uk"},
                {"text": "↩", "callback_data": f"d:t:{draft_id}:back"},
            ]
        ]
    }


def _contact_link(contact) -> str:
    """Clickable name that opens the person's chat: t.me/username is the
    reliable path (tg://user?id renders unclickable for unknown users)."""
    name = _esc(contact.full_name)
    handle = (contact.telegram or "").strip().lstrip("@")
    if handle and " " not in handle and "://" not in handle:
        return f'<a href="https://t.me/{_esc(handle)}">{name}</a>'
    if contact.telegram_chat_id:
        return f'<a href="tg://user?id={contact.telegram_chat_id}">{name}</a>'
    return name


# Channels-message id → contact id, so a reply to it saves new channels.
_channel_msgs: dict[int, int] = {}


def _channels_text(contact, draft_text: str) -> str:
    """All known channels for reaching this person elsewhere + the draft in
    a tap-to-copy block."""
    lines = [f"📇 <b>{_esc(contact.full_name)} — канали</b>", ""]
    pairs = [
        ("Telegram", contact.telegram),
        ("Телефон", contact.phone),
        ("Email", contact.email),
        ("WhatsApp", contact.whatsapp),
        ("Viber", contact.viber),
        ("Instagram", contact.instagram_url),
        ("LinkedIn", contact.linkedin_url),
        ("Facebook", contact.facebook_url),
        ("Twitter/X", contact.twitter_url),
        ("YouTube", contact.youtube_url),
        ("GitHub", contact.github_url),
        ("Сайт", contact.website_url),
    ]
    known = [(k, v) for k, v in pairs if v]
    if known:
        for k, v in known:
            lines.append(f"• {k}: {_esc(str(v))}")
    else:
        lines.append("<i>Інших каналів не знаю — додай у веб-інтерфейсі.</i>")
    if draft_text.strip():
        lines.append("")
        lines.append("Повідомлення (тапни, щоб скопіювати):")
        lines.append(f"<code>{_esc(draft_text)}</code>")
    lines.append("")
    lines.append(
        "<i>↩️ Reply на це повідомлення: email / телефон / лінк на соцмережу / "
        "фото візитки — збережу в картку контакту.</i>"
    )
    return "\n".join(lines)


def _outreach_card(contact, draft) -> str:
    """Queue card: who, why now, last touch, facts — then the draft."""
    head = f"👤 <b>{_contact_link(contact)}</b>"
    if contact.telegram:
        head += f" ({_esc(contact.telegram)})"
    head += (
        f" · {_esc(contact.relationship_type.value)}"
        f" · {_esc(contact.warmth_status)} {round(contact.warmth_score)}"
    )
    if service.effective_importance(contact) >= 3:
        head += " · ⭐ важливий"
    lines = [head, "", f"📊 <b>Чому зараз:</b> {_esc(draft.incoming_text)}"]

    from app.modules.goals.service import active_goals_for_contact

    goals = active_goals_for_contact(contact)
    if goals:
        lines.append("🎯 <b>Ціль:</b> " + ", ".join(_esc(g.title) for g in goals[:2]))

    last = next((i for i in contact.interactions if i.summary), None)
    if last:
        when = last.occurred_at.strftime("%d.%m.%Y")
        lines.append(f"🕓 <b>Останнє:</b> {when} — {_esc(last.summary[:160])}")

    facts = [f for f in getattr(contact, "facts", []) if f.is_current][:3]
    if facts:
        lines.append("💡 " + "; ".join(_esc(f.value) for f in facts))

    lines.append("")
    if draft.draft_text.strip():
        lines.append(f"✍️ <b>Чернетка:</b>\n{_esc(draft.draft_text)}")
        lines.append("")
        lines.append("<i>Reply текстом/голосом — скоригую чернетку.</i>")
    else:
        lines.append("<i>Чернетки немає (AI недоступний) — напиши сам або пропусти.</i>")
    return "\n".join(lines)


def _render_draft(contact, draft, is_new: bool = False) -> str:
    from .models import DraftKind

    if draft.kind == DraftKind.outreach:
        return _outreach_card(contact, draft)
    return _preview_text(contact, draft, is_new)


def _send_next_outreach_card(client, db, admin: int) -> bool:
    """Advance the queue: draft the next due contact and send its card.
    Returns False when the queue is empty (and tells the admin)."""
    connection = service.get_enabled_connection(db)
    if connection is None:
        client.send_message(
            admin,
            "Ще не бачу Business-з'єднання. Воно підхопиться саме собою з "
            "першим вхідним повідомленням — або перемкни бота в "
            "Налаштування → Telegram Business → Чат-боти (вимкнути/увімкнути).",
        )
        return False
    nxt = service.next_outreach_contact(db)
    if nxt is None:
        from datetime import datetime, timezone

        from app.modules.telegram_bot.models import DraftKind, DraftStatus, TelegramDraft
        from sqlalchemy import func, select

        today_start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        sent = db.scalar(
            select(func.count(TelegramDraft.id)).where(
                TelegramDraft.kind == DraftKind.outreach,
                TelegramDraft.created_at >= today_start,
                TelegramDraft.status == DraftStatus.sent,
            )
        )
        client.send_message(
            admin,
            f"🎉 Черга на сьогодні порожня. Надіслано: {sent or 0}. "
            "Всі, хто був прострочений і доступний у Telegram, опрацьовані.",
        )
        return False
    contact, reason = nxt
    # Make the card clickable/complete: pull username+birthday from Telegram
    # if we still don't have a handle for this export-imported contact.
    if not (contact.telegram or "").strip():
        try:
            service.enrich_from_telegram(db, client, contact)
        except Exception as exc:  # pragma: no cover
            logger.warning("enrich failed for %s: %s", contact.id, exc)
    draft = service.create_outreach_draft(db, contact, connection, reason)
    sent = client.send_message(
        admin,
        _outreach_card(contact, draft),
        reply_markup=_draft_keyboard(
            draft.id, bool(draft.draft_text.strip()), outreach=True
        ),
    )
    if sent:
        service.set_admin_message(db, draft, sent.get("message_id", 0))
    return True


def _preview_text(contact, draft, is_new: bool) -> str:
    head = f"👤 <b>{_contact_link(contact)}</b>"
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
            # Messaging someone directly closes any reminder about them.
            from app.modules.automation import reminders as _reminders

            _reminders.complete_for_contact(db, contact.id)
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
        if draft is None:
            return  # conversation-ender: logged, no reply needed
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
    admin = _admin_id()

    if data == "q:start":
        client.answer_callback(cb_id, "Починаю обхід")
        if admin:
            with SessionLocal() as db:
                _send_next_outreach_card(client, db, admin)
        return

    if not data.startswith("d:"):
        client.answer_callback(cb_id)
        return
    try:
        parts = data.split(":")
        action = parts[1]
        draft_id = int(parts[2])
        arg = parts[3] if len(parts) > 3 else None
    except (ValueError, IndexError):
        client.answer_callback(cb_id)
        return

    with SessionLocal() as db:
        draft = service.get_draft(db, draft_id)
        if draft is None or draft.status != DraftStatus.pending:
            client.answer_callback(cb_id, "Уже неактуально")
            return
        from .models import DraftKind

        is_outreach = draft.kind == DraftKind.outreach
        handled = False

        # ── Non-terminal actions (the card stays pending) ────────────────
        if action == "c":
            contact = db.get(Contact, draft.contact_id)
            client.answer_callback(cb_id)
            if contact and admin:
                sent = client.send_message(
                    admin, _channels_text(contact, draft.draft_text)
                )
                if sent:
                    _channel_msgs[sent.get("message_id", 0)] = contact.id
                    if len(_channel_msgs) > 200:
                        for k in list(_channel_msgs)[:100]:
                            _channel_msgs.pop(k, None)
            return
        if action == "t":
            contact = db.get(Contact, draft.contact_id)
            if arg is None:
                client.answer_callback(cb_id, "Обери мову")
                if msg:
                    client.edit_message_text(
                        msg["chat"]["id"],
                        msg["message_id"],
                        _render_draft(contact, draft),
                        reply_markup=_translate_keyboard(draft.id),
                    )
                return
            kb = _draft_keyboard(draft.id, True, outreach=is_outreach)
            if arg == "back":
                client.answer_callback(cb_id)
                if msg:
                    client.edit_message_text(
                        msg["chat"]["id"],
                        msg["message_id"],
                        _render_draft(contact, draft),
                        reply_markup=kb,
                    )
                return
            from app.modules.insights import ai as _ai

            translated = _ai.translate_message(draft.draft_text, arg)
            if translated is None:
                client.answer_callback(cb_id, "Не вдалося перекласти")
                return
            service.update_draft_text(db, draft, translated)
            client.answer_callback(cb_id, "Перекладено")
            if msg:
                client.edit_message_text(
                    msg["chat"]["id"],
                    msg["message_id"],
                    _render_draft(contact, draft),
                    reply_markup=kb,
                )
            return
        if action == "x":
            contact = db.get(Contact, draft.contact_id)
            if contact:
                service.stop_list(db, contact)
            service.mark(db, draft, DraftStatus.skipped)
            client.answer_callback(cb_id, "У стоп-листі 🚫 (повернути — у веб-UI)")
            if msg:
                client.delete_message(msg["chat"]["id"], msg["message_id"])
            if is_outreach and admin:
                _send_next_outreach_card(client, db, admin)
            return

        if action == "s":
            ok = service.approve_and_send(db, client, draft)
            client.answer_callback(cb_id, "Надіслано ✅" if ok else "Помилка надсилання")
            if ok and msg:
                client.delete_message(msg["chat"]["id"], msg["message_id"])
            handled = ok
        elif action == "m":
            service.mark(db, draft, DraftStatus.manual)
            client.answer_callback(cb_id, "Ок, відповідай сам")
            if msg:
                client.delete_message(msg["chat"]["id"], msg["message_id"])
            handled = True
        elif action == "k":
            service.mark(db, draft, DraftStatus.skipped)
            client.answer_callback(cb_id, "Пропущено")
            if msg:
                client.delete_message(msg["chat"]["id"], msg["message_id"])
            handled = True
        else:
            client.answer_callback(cb_id)

        # The outreach queue flows card-to-card: any decision advances it.
        if is_outreach and handled and admin:
            _send_next_outreach_card(client, db, admin)


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
        # Reply to a 📇 channels message → save new channels to the contact.
        if reply_to in _channel_msgs:
            _handle_channel_reply(client, admin, _channel_msgs[reply_to], msg)
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
            from .models import DraftKind as _DK

            kb = _draft_keyboard(draft.id, True, outreach=draft.kind == _DK.outreach)
            edited = client.edit_message_text(
                admin,
                reply_to,
                _render_draft(contact, draft),
                reply_markup=kb,
            )
            if not edited:
                sent = client.send_message(
                    admin,
                    _render_draft(contact, draft),
                    reply_markup=kb,
                )
                if sent:
                    service.set_admin_message(db, draft, sent.get("message_id", 0))
        return

    if _is_legacy_button(text):
        client.send_message(
            admin,
            "Старе меню Chater більше не використовується — прибрав клавіатуру. "
            "Актуальні команди: /help",
            reply_markup=_REMOVE_KEYBOARD,
        )
        return

    if text.startswith("/"):
        _handle_command(client, admin, text)
        return

    # Voice note (not a reply) = intake: "запиши, що я познайомився з ..."
    if msg.get("voice"):
        audio = client.download_file(msg["voice"].get("file_id", ""))
        transcript = transcribe_ogg(audio) if audio else None
        if not transcript:
            client.send_message(
                admin,
                "Не зміг розшифрувати голосове (потрібен OPENAI_API_KEY або "
                "GEMINI_API_KEY).",
            )
            return
        _handle_voice_intake(client, admin, transcript)
        return

    # Plain text: first try to interpret it as an assistant command
    # (reminder / note / cadence / importance); otherwise search the network.
    if text.strip():
        if _handle_assistant_intent(client, admin, text.strip()):
            return
        _handle_network_search(client, admin, text.strip())


def _handle_channel_reply(client, admin: int, contact_id: int, msg: dict) -> None:
    """Reply to a channels card: text with links/email/phone, or a
    business-card photo — everything lands in the contact record."""
    with SessionLocal() as db:
        contact = db.get(Contact, contact_id)
        if contact is None:
            return

        parsed: dict = {}
        photo = msg.get("photo") or []
        document = msg.get("document") or {}
        if photo or str(document.get("mime_type", "")).startswith("image/"):
            file_id = (
                photo[-1].get("file_id", "") if photo else document.get("file_id", "")
            )
            image = client.download_file(file_id) if file_id else None
            if image:
                from app.modules.insights import ai as _ai

                parsed = _ai.parse_business_card(image) or {}
            if not parsed:
                client.send_message(
                    admin,
                    "Не зміг розпізнати візитку. Надішли дані текстом — "
                    "email, телефон чи лінк.",
                )
                return
        else:
            text = msg.get("text") or msg.get("caption") or ""
            if not text and msg.get("voice"):
                audio = client.download_file(msg["voice"].get("file_id", ""))
                text = transcribe_ogg(audio) if audio else ""
            parsed = service.parse_channel_text(text or "")

        saved = service.apply_channels(db, contact, parsed)
        if saved:
            client.send_message(
                admin,
                f"✅ Зберіг для <b>{_contact_link(contact)}</b>: "
                + ", ".join(saved),
            )
        else:
            client.send_message(
                admin,
                "Не знайшов у повідомленні email/телефону/лінків. "
                "Приклад: instagram.com/nick, +420123456789, nick@mail.com",
            )


def _handle_voice_intake(client, admin: int, transcript: str) -> None:
    from app.modules.insights import ai as _ai

    parsed = _ai.parse_voice_intake(transcript)
    if parsed is None:
        client.send_message(
            admin,
            "Почув: «" + _esc(transcript[:300]) + "»\n\n"
            "Не зміг розібрати, про кого це (або AI недоступний). "
            "Спробуй назвати ім'я людини явно.",
        )
        return
    with SessionLocal() as db:
        contact, created, facts_added = service.apply_intake(db, parsed)
        status = "🆕 створив контакт" if created else "оновив контакт"
        lines = [
            f"✅ {status}: <b>{_contact_link(contact)}</b>",
        ]
        role = " · ".join(filter(None, [contact.position, contact.company]))
        if role:
            lines.append(f"💼 {_esc(role)}")
        if facts_added:
            lines.append(f"💡 Фактів записано: {facts_added}")
        note = (parsed.get("note") or "").strip()
        if note:
            lines.append(f"📝 {_esc(note[:200])}")
        client.send_message(admin, "\n".join(lines))


_WEEKDAYS_UK = [
    "понеділок", "вівторок", "середа", "четвер", "пʼятниця", "субота", "неділя",
]


def _due_from_iso(s: str):
    """ISO date string → a due datetime at 09:00 UTC, or None if unparseable."""
    from datetime import date as _date, datetime, time, timezone

    s = (s or "").strip()
    if not s:
        return None
    try:
        d = _date.fromisoformat(s[:10])
    except ValueError:
        return None
    return datetime.combine(d, time(9, 0, tzinfo=timezone.utc))


def _handle_assistant_intent(client, admin: int, text: str) -> bool:
    """Nexus-style: interpret a free-text message as a command over a contact
    (reminder / note / cadence / importance) and act on it. Returns True when
    handled; False means 'not a command' → caller falls back to search."""
    from datetime import datetime, timezone

    from app.modules.insights import ai as _ai

    now = datetime.now(timezone.utc)
    today = f"{now.date().isoformat()}, {_WEEKDAYS_UK[now.weekday()]}"
    intent = _ai.parse_assistant_intent(text, today)
    if not intent:
        return False
    action = intent.get("action")
    if action not in ("remind", "note", "cadence", "importance"):
        return False

    person = (intent.get("person") or "").strip()
    with SessionLocal() as db:
        contact = service.find_contact_by_name(db, person) if person else None
        if contact is None:
            # Couldn't resolve the person → let network search try instead.
            return False

        if action == "remind":
            due = _due_from_iso(intent.get("due_date", ""))
            if due is None:
                return False
            from app.modules.automation import reminders as _reminders

            what = (intent.get("text") or "").strip() or (
                f"написати {contact.full_name}"
            )
            _reminders.create_reminder(db, contact, what, due)
            client.send_message(
                admin,
                f"⏰ Нагадаю: <b>{_esc(what)}</b>\n"
                f"👤 {_contact_link(contact)} · {due.date().isoformat()}",
            )
            return True

        if action == "note":
            note = (intent.get("text") or "").strip()
            if not note:
                return False
            from datetime import datetime as _dt, timezone as _tz

            stamp = _dt.now(_tz.utc).strftime("%d.%m.%Y")
            contact.notes = (
                f"{contact.notes}\n[{stamp}] {note}"
                if contact.notes
                else f"[{stamp}] {note}"
            )
            db.commit()
            client.send_message(
                admin,
                f"📝 Записав до <b>{_contact_link(contact)}</b>:\n{_esc(note)}",
            )
            return True

        if action == "cadence":
            from app.modules.contacts.models import Frequency

            freq = (intent.get("frequency") or "").strip()
            try:
                contact.contact_frequency = Frequency(freq)
            except ValueError:
                return False
            from app import warmth

            warmth.refresh(contact)
            db.commit()
            client.send_message(
                admin,
                f"🔁 Каденція для <b>{_contact_link(contact)}</b>: "
                f"{_esc(freq)}.",
            )
            return True

        if action == "importance":
            imp = int(intent.get("importance") or 0)
            if imp not in (1, 2, 3):
                return False
            contact.importance = imp
            db.commit()
            stars = "⭐" * imp
            client.send_message(
                admin,
                f"{stars} Важливість <b>{_contact_link(contact)}</b>: {imp}/3.",
            )
            return True

    return False


def _handle_network_search(client, admin: int, query: str) -> None:
    from app import crud
    from app.modules.insights import ai as _ai

    from app.modules.search import service as search_service

    with SessionLocal() as db:
        # Semantic first: rank by embedding, then narrow the AI 'why' to the
        # top candidates (cheaper + better than dumping the whole network).
        hits = search_service.semantic_search(db, query, k=12)
        if hits:
            by_id = {cid: crud.get_contact(db, cid) for cid, _ in hits}
            by_id = {k: v for k, v in by_id.items() if v is not None}
            corpus = []
            for cid, _score in hits:
                c = by_id.get(cid)
                if c is None:
                    continue
                facts = "; ".join(
                    f.value for f in getattr(c, "facts", []) if f.is_current
                )[:200]
                corpus.append(
                    f"{c.id} | {c.full_name} | "
                    f"{' · '.join(filter(None, [c.position, c.company]))} | "
                    f"{c.location or ''} | {', '.join(t.name for t in c.tags)} | "
                    f"{facts} | {(c.notes or '')[:120]}"
                )
            matches = _ai.search_network(query, corpus)
            if matches is None:
                # AI off → return the semantic ranking directly.
                lines = [f"🔎 <b>«{_esc(query)}»</b> (семантичний пошук)"]
                for cid, _score in hits[:8]:
                    c = by_id.get(cid)
                    if c:
                        lines.append(f"• {_contact_link(c)}")
                client.send_message(admin, "\n".join(lines))
                return
            _render_search_matches(client, admin, query, matches, by_id)
            return

        # No embeddings yet → whole-network corpus (or substring if AI off).
        contacts = crud.list_contacts(db, sort="name")
        corpus = []
        by_id = {}
        for c in contacts:
            by_id[c.id] = c
            facts = "; ".join(
                f.value for f in getattr(c, "facts", []) if f.is_current
            )[:200]
            corpus.append(
                f"{c.id} | {c.full_name} | "
                f"{' · '.join(filter(None, [c.position, c.company]))} | "
                f"{c.location or ''} | {', '.join(t.name for t in c.tags)} | "
                f"{facts} | {(c.notes or '')[:120]}"
            )
        matches = _ai.search_network(query, corpus)
        if matches is None:
            # AI off → plain substring search as a fallback.
            found = crud.list_contacts(db, search=query, sort="name")
            if not found:
                client.send_message(admin, f"Нічого не знайшов за «{_esc(query)}».")
                return
            lines = [f"<b>Збіги за «{_esc(query)}»</b> (простий пошук)"]
            for c in found[:10]:
                lines.append(f"• {_contact_link(c)}")
            client.send_message(admin, "\n".join(lines))
            return
        _render_search_matches(client, admin, query, matches, by_id)


def _render_search_matches(client, admin, query, matches, by_id):
    if not matches:
        client.send_message(admin, f"У мережі не знайшов нікого під «{_esc(query)}».")
        return
    lines = [f"🔎 <b>«{_esc(query)}»</b>"]
    for m in matches[:8]:
        c = by_id.get(m.get("contact_id"))
        if c is None:
            continue
        role = " · ".join(filter(None, [c.position, c.company]))
        lines.append("")
        lines.append(
            f"👤 <b>{_contact_link(c)}</b>" + (f" — {_esc(role)}" if role else "")
        )
        lines.append(f"<i>{_esc(m.get('why', ''))}</i>")
    client.send_message(admin, "\n".join(lines))


def _fmt_date(dt) -> str:
    from datetime import timezone

    if dt is None:
        return "?"
    if getattr(dt, "tzinfo", None) is None and hasattr(dt, "date"):
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.strftime("%d.%m.%Y")


def _timeline_text(db, contact) -> str:
    """Everything we know about the relationship, in one glance: history
    endpoints, open reminders, live facts, recent life events, notes."""
    from app import warmth
    from app.modules.automation import reminders as _reminders
    from app.modules.telegram_bot.service import effective_importance

    role = " · ".join(filter(None, [contact.position, contact.company]))
    imp = effective_importance(contact)
    header = f"🧭 <b>{_contact_link(contact)}</b>"
    if role:
        header += f"\n💼 {_esc(role)}"
    header += (
        f"\n📶 {contact.warmth_status} ({round(contact.warmth_score)})"
        + (f" · {'⭐' * imp}" if imp else "")
    )
    lines = [header]

    itx = sorted(contact.interactions, key=lambda i: i.occurred_at)
    if itx:
        lines.append("")
        lines.append("<b>Історія</b>")
        first = itx[0]
        lines.append(
            f"• Перша: {_fmt_date(first.occurred_at)}"
            + (f" — {_esc((first.summary or '')[:80])}" if first.summary else "")
        )
        if len(itx) > 1:
            last = itx[-1]
            lines.append(
                f"• Остання: {_fmt_date(last.occurred_at)}"
                + (f" — {_esc((last.summary or '')[:80])}" if last.summary else "")
            )
        lines.append(f"• Всього дотиків: {len(itx)}")

    open_r = [r for r in _reminders.open_reminders(db) if r.contact_id == contact.id]
    if open_r:
        lines.append("")
        lines.append("<b>⏰ Нагадування</b>")
        for r in open_r[:5]:
            lines.append(f"• {_esc(r.text)} ({_fmt_date(r.due_at)})")

    facts = [f for f in getattr(contact, "facts", []) if f.is_current]
    if facts:
        lines.append("")
        lines.append("<b>Факти</b>")
        for f in facts[:8]:
            lines.append(f"• {_esc(f.value[:120])}")

    events = sorted(
        contact.life_events, key=lambda e: e.created_at, reverse=True
    )
    if events:
        lines.append("")
        lines.append("<b>Події</b>")
        for e in events[:4]:
            lines.append(f"• {_esc(e.title)} ({_fmt_date(e.created_at)})")

    if contact.birth_date:
        lines.append("")
        lines.append(f"🎂 День народження: {contact.birth_date.strftime('%d.%m')}")

    if contact.notes:
        lines.append("")
        lines.append("<b>Нотатки</b>")
        lines.append(f"<i>{_esc(contact.notes[-400:])}</i>")

    return "\n".join(lines)


def _handle_command(client, admin: int, text: str) -> None:
    from app import crud, dashboard, models, warmth
    from app.modules.automation import telegram as tg

    cmd, _, arg = text.strip().partition(" ")
    cmd = cmd.lower().lstrip("/").split("@")[0]

    with SessionLocal() as db:
        if cmd in ("start", "help", "menu"):
            client.send_message(
                admin,
                "<b>Networking AI</b>\n"
                "/queue — почати обхід (кому написати, з чернетками)\n"
                "/goals — активні цілі та причетні люди\n"
                "/embed — проіндексувати мережу для розумного пошуку\n"
                "/enrich — підтягнути юзернейми/дні народження з Telegram\n"
                "/today — дайджест дня\n"
                "/upcoming — що попереду (дні народження, події)\n"
                "/birthdays — найближчі дні народження\n"
                "/events — що нового в людей\n"
                "/reconnect — з ким варто відновити звʼязок\n"
                "/reflect — подумати про стосунки (AI)\n"
                "/reminders — активні нагадування\n"
                "/due — всі прострочені\n"
                "/find &lt;ім'я&gt; — пошук за іменем\n"
                "/timeline &lt;ім'я&gt; — вся історія стосунку\n"
                "/similar &lt;ім'я&gt; — схожі та повʼязані люди\n"
                "/activity — що робив бот + стан системи\n\n"
                "🤖 Пиши боту як асистенту:\n"
                "• «нагадай написати Олегу через 3 тижні»\n"
                "• «запиши до Марії, що вона переїхала в Берлін»\n"
                "• «спілкуватися з Іваном раз на місяць»\n\n"
                "💬 Або постав питання — пошук по мережі "
                "(«хто з моїх шарить у крипті?»)\n"
                "🎤 Голосове — запишу в базу («познайомився з Андрієм, "
                "робить фінтех...»)\n\n"
                "Вхідні з Telegram Business приходять сюди з чернеткою "
                "відповіді: ✅ надіслати · reply — скоригувати.",
                reply_markup=_REMOVE_KEYBOARD,
            )
        elif cmd in ("queue", "obhid"):
            _send_next_outreach_card(client, db, admin)
        elif cmd == "enrich":
            pending = service.pending_enrichment(db, limit=25)
            if not pending:
                client.send_message(
                    admin, "Усі доступні контакти вже мають юзернейми ✅"
                )
                return
            done = 0
            for c in pending:
                try:
                    if service.enrich_from_telegram(db, client, c):
                        done += 1
                except Exception:
                    pass
            remaining = len(service.pending_enrichment(db, limit=1000))
            client.send_message(
                admin,
                f"🔄 Оновив {done} із {len(pending)} (username/ДН/біо з Telegram). "
                f"Ще без юзернейма: ~{remaining}. Запусти /enrich ще раз для наступної пачки."
                + ("" if done else "\n\n⚠️ Нічого не витягнулось — можливо, getChat "
                   "не бачить цих людей (бот з ними ще не взаємодіяв). "
                   "Тоді юзернейми підтягнуться самі, коли вони тобі напишуть."),
            )
        elif cmd == "embed":
            from app.modules.search import service as search_service
            from app.modules.insights import llm as _llm

            if not _llm.embeddings_enabled():
                client.send_message(
                    admin,
                    "Ембединги вимкнені — додай OPENAI_API_KEY (або VOYAGE_API_KEY) у .env.",
                )
                return
            done = search_service.embed_pending(db, limit=200)
            remaining = search_service.pending_count(db)
            client.send_message(
                admin,
                f"🧠 Проіндексував {done}. Ще без індексу: ~{remaining}. "
                + ("Готово — семантичний пошук увімкнено." if not remaining
                   else "Запусти /embed ще раз для наступної пачки."),
            )
        elif cmd == "goals":
            from app.modules.goals.service import list_goals
            from app.modules.goals.models import GoalStatus

            goals = list_goals(db, status=GoalStatus.active)
            if not goals:
                client.send_message(admin, "Немає активних цілей. Створи у веб-інтерфейсі (Goals).")
                return
            lines = ["🎯 <b>Активні цілі</b>"]
            for g in goals:
                lines.append(f"• {_esc(g.title)} — {len(g.contacts)} контакт(ів)")
            client.send_message(admin, "\n".join(lines))
        elif cmd == "overdue":
            _handle_command(client, admin, "/due")
        elif cmd in ("today", "network", "digest", "weekly", "monthly"):
            client.send_message(
                admin,
                tg.digest_text(dashboard.build_dashboard(db)),
                reply_markup={
                    "inline_keyboard": [
                        [{"text": "🚀 Почати обхід", "callback_data": "q:start"}]
                    ]
                },
            )
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
        elif cmd in ("upcoming", "naperec", "ahead"):
            data = dashboard.build_dashboard(db)
            if not data.upcoming:
                client.send_message(admin, "Найближчим часом — жодних дат попереду ✦")
                return
            lines = ["🔮 <b>Наперед</b>"]
            for u in data.upcoming:
                when = "сьогодні" if u.days_away == 0 else f"через {u.days_away}д"
                label = (
                    "🎂 день народження" if u.label == "Birthday" else _esc(u.label)
                )
                lines.append(f"• {_esc(u.contact.full_name)} — {label} ({when})")
            client.send_message(admin, "\n".join(lines))
        elif cmd in ("birthdays", "bdays", "dr"):
            data = dashboard.build_dashboard(db)
            bdays = [u for u in data.upcoming if u.label == "Birthday"]
            if not bdays:
                client.send_message(admin, "Найближчим часом днів народження немає 🎂")
                return
            lines = ["🎂 <b>Дні народження</b>"]
            for u in bdays:
                when = "сьогодні! 🎉" if u.days_away == 0 else f"через {u.days_away}д"
                lines.append(f"• {_esc(u.contact.full_name)} — {when}")
            client.send_message(admin, "\n".join(lines))
        elif cmd in ("events", "updates"):
            from sqlalchemy import select

            events = list(
                db.scalars(
                    select(models.LifeEvent)
                    .where(models.LifeEvent.status == models.LifeEventStatus.new)
                    .order_by(models.LifeEvent.created_at.desc())
                )
            )
            if not events:
                client.send_message(admin, "Нових оновлень по людях поки немає ✦")
                return
            lines = ["📰 <b>Що нового в людей</b>"]
            for e in events[:20]:
                who = e.contact.full_name if e.contact else "?"
                lines.append(f"• <b>{_esc(who)}</b> — {_esc(e.title)}")
            client.send_message(admin, "\n".join(lines))
        elif cmd in ("reconnect", "reconnects"):
            from app.modules.telegram_bot.service import effective_importance

            due = [
                c
                for c in crud.list_contacts(db, sort="due")
                if warmth.is_due(c) and not c.do_not_contact
            ]
            if not due:
                client.send_message(admin, "Нікого повторно піймати не треба зараз ✦")
                return
            due.sort(
                key=lambda c: (effective_importance(c), warmth.overdue_ratio(c)),
                reverse=True,
            )
            lines = ["🔁 <b>Варто відновити звʼязок</b>"]
            for c in due[:15]:
                d = round(warmth.days_since_last_contact(c))
                star = "⭐ " if effective_importance(c) >= 3 else ""
                lines.append(f"• {star}{_esc(c.full_name)} — {d}д ({c.warmth_status})")
            client.send_message(
                admin,
                "\n".join(lines),
                reply_markup={
                    "inline_keyboard": [
                        [{"text": "🚀 Почати обхід", "callback_data": "q:start"}]
                    ]
                },
            )
        elif cmd in ("reminders", "remind"):
            from app.modules.automation import reminders as _reminders

            open_r = _reminders.open_reminders(db)
            if not open_r:
                client.send_message(
                    admin,
                    "Активних нагадувань немає.\n\n"
                    "Постав природною мовою: «нагадай написати Олегу через "
                    "3 тижні».",
                )
                return
            from datetime import datetime, timezone

            now = datetime.now(timezone.utc)
            lines = ["⏰ <b>Нагадування</b>"]
            for r in open_r[:20]:
                due = r.due_at if r.due_at.tzinfo else r.due_at.replace(tzinfo=timezone.utc)
                days = (due.date() - now.date()).days
                when = (
                    "сьогодні"
                    if days == 0
                    else (f"прострочено на {-days}д" if days < 0 else f"через {days}д")
                )
                who = r.contact.full_name if r.contact else "—"
                lines.append(f"• {_esc(r.text)} — <b>{_esc(who)}</b> ({when})")
            client.send_message(admin, "\n".join(lines))
        elif cmd in ("activity", "status"):
            from datetime import datetime, timedelta, timezone
            from sqlalchemy import select

            now = datetime.now(timezone.utc)
            week = now - timedelta(days=7)

            def _aware(dt):
                return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

            all_contacts = list(db.scalars(select(models.Contact)).unique())
            new_c = [c for c in all_contacts if _aware(c.created_at) >= week]
            events = list(
                db.scalars(
                    select(models.LifeEvent).order_by(
                        models.LifeEvent.created_at.desc()
                    )
                )
            )
            recent_ev = [e for e in events if _aware(e.created_at) >= week]

            lines = ["🛠 <b>Активність бота</b>"]
            lines.append("")
            lines.append(f"👥 Нових контактів за тиждень: <b>{len(new_c)}</b>")
            for c in new_c[:5]:
                src = ", ".join(t.name for t in c.tags) or "—"
                lines.append(f"  • {_esc(c.full_name)} <i>({_esc(src)})</i>")
            lines.append(f"🎉 Нових подій за тиждень: <b>{len(recent_ev)}</b>")
            for e in recent_ev[:3]:
                who = e.contact.full_name if e.contact else "?"
                lines.append(f"  • {_esc(who)} — {_esc(e.title)}")

            from app.modules.automation import reminders as _reminders
            from app.modules.search import service as search_service
            from app.modules.insights import llm as _llm
            from app.integrations import google as _google

            open_r = len(_reminders.open_reminders(db))
            g = _google.status(db)
            prov = _llm.active_provider() or "вимкнено"
            pending = search_service.pending_count(db)

            lines.append("")
            lines.append("<b>Стан</b>")
            lines.append(f"📇 Всього контактів: {len(all_contacts)}")
            lines.append(f"⏰ Відкритих нагадувань: {open_r}")
            lines.append(f"🤖 AI-провайдер: {_esc(prov)}")
            lines.append(f"🧠 Не проіндексовано: {pending}")
            lines.append(
                "📧 Google: " + ("підключено ✅" if g.get("connected") else "ні")
            )
            lines.append(
                "✈️ Telegram: "
                + ("налаштовано ✅" if settings.telegram_configured else "ні")
            )
            client.send_message(admin, "\n".join(lines))
        elif cmd in ("similar", "related"):
            if not arg.strip():
                client.send_message(admin, "Використання: /similar &lt;ім'я&gt;")
                return
            contact = service.find_contact_by_name(db, arg.strip())
            if contact is None:
                client.send_message(admin, f"Не знайшов контакт «{_esc(arg)}».")
                return
            from app.modules.search import service as search_service

            lines = [f"👥 <b>Схожі на {_esc(contact.full_name)}</b>"]
            hits = search_service.similar_contacts(db, contact.id, k=5)
            shown: set[int] = set()
            for cid, score in hits:
                c = crud.get_contact(db, cid)
                if c is None:
                    continue
                shown.add(c.id)
                role = " · ".join(filter(None, [c.position, c.company]))
                lines.append(
                    f"• {_contact_link(c)}" + (f" — {_esc(role)}" if role else "")
                )
            # Explicit links: same company or a shared goal (no AI needed).
            related = []
            if contact.company:
                for c in crud.list_contacts(db, sort="name"):
                    if (
                        c.id != contact.id
                        and c.id not in shown
                        and (c.company or "").strip().casefold()
                        == contact.company.strip().casefold()
                    ):
                        related.append((c, f"колега — {contact.company}"))
            for g in getattr(contact, "goals", []):
                for c in g.contacts:
                    if c.id != contact.id and c.id not in shown:
                        related.append((c, f"ціль — {g.title}"))
            if related:
                lines.append("")
                lines.append("<b>Прямі звʼязки</b>")
                seen: set[int] = set()
                for c, why in related[:8]:
                    if c.id in seen:
                        continue
                    seen.add(c.id)
                    lines.append(f"• {_contact_link(c)} — <i>{_esc(why)}</i>")
            if len(lines) == 1:
                lines.append(
                    "Поки нікого схожого. Проіндексуй мережу — /embed — "
                    "для семантичних збігів."
                )
            client.send_message(admin, "\n".join(lines))
        elif cmd in ("reflect", "reflection"):
            from app.modules.automation import reviews

            contacts = reviews.pick_reflection_contacts(
                db, settings.reflection_count
            )
            if not contacts:
                client.send_message(admin, "Поки нема над чим рефлексувати ✦")
                return
            text = reviews.reflection_text(db, contacts)
            client.send_message(
                admin,
                text or "AI недоступний — рефлексія потребує ключа (OpenAI/Anthropic).",
            )
        elif cmd in ("timeline", "history"):
            if not arg.strip():
                client.send_message(admin, "Використання: /timeline &lt;ім'я&gt;")
                return
            contact = service.find_contact_by_name(db, arg.strip())
            if contact is None:
                client.send_message(admin, f"Не знайшов контакт «{_esc(arg)}».")
                return
            client.send_message(admin, _timeline_text(db, contact))
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
