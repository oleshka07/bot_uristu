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

    # Plain text = natural-language search over the network.
    if text.strip():
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


def _handle_network_search(client, admin: int, query: str) -> None:
    from app import crud
    from app.modules.insights import ai as _ai

    with SessionLocal() as db:
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
        if not matches:
            client.send_message(
                admin, f"У мережі не знайшов нікого під «{_esc(query)}»."
            )
            return
        lines = [f"🔎 <b>«{_esc(query)}»</b>"]
        for m in matches[:8]:
            c = by_id.get(m.get("contact_id"))
            if c is None:
                continue
            role = " · ".join(filter(None, [c.position, c.company]))
            lines.append("")
            lines.append(
                f"👤 <b>{_contact_link(c)}</b>"
                + (f" — {_esc(role)}" if role else "")
            )
            lines.append(f"<i>{_esc(m.get('why', ''))}</i>")
        client.send_message(admin, "\n".join(lines))


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
                "/queue — почати обхід (кому написати, з чернетками)\n"
                "/enrich — підтягнути юзернейми/дні народження з Telegram\n"
                "/today — дайджест дня\n"
                "/due — всі прострочені\n"
                "/find &lt;ім'я&gt; — пошук за іменем\n\n"
                "💬 Просто напиши питання — пошук по мережі "
                "(«хто з моїх шарить у крипті?»)\n"
                "🎤 Голосове — запишу в базу («познайомився з Андрієм, "
                "робить фінтех...»)\n\n"
                "Вхідні з Telegram Business приходять сюди з чернеткою "
                "відповіді: ✅ надіслати · reply — скоригувати.",
            )
        elif cmd == "queue":
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
        elif cmd in ("today", "network", "digest"):
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
