"""Інструменти MCP: що Claude може прочитати і що зберегти.

Принцип: один інструмент віддає контекст (голос власника, памʼять про людину),
один зберігає готовий текст дослівно, решта — читання й дії. Жоден не
запускає нашу генерацію. Вивід — компактний текст, не сирий JSON: модель
читає його краще, а контекст не вигорає.

Помилка інструмента — це ``ToolError`` з дієвим текстом («у контакту немає
Telegram, є email — збережи листом»), а не виняток протоколу.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.contacts.models import Contact


class ToolError(Exception):
    """Дієва помилка для моделі: що не так і що зробити натомість."""


# ── Допоміжне ────────────────────────────────────────────────────────────────

_ID_RE = re.compile(r"^#?(\d+)$")


def _int(value, default: int, lo: int, hi: int) -> int:
    try:
        return max(lo, min(hi, int(value)))
    except (TypeError, ValueError):
        return default


def _clip(text: str | None, n: int) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= n else text[: n - 1] + "…"


def _when(value: datetime | date | None) -> str:
    if value is None:
        return "?"
    if isinstance(value, datetime):
        return value.strftime("%d.%m.%Y")
    return value.strftime("%d.%m.%Y")


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError as exc:
        raise ToolError(f"Дата має бути у форматі YYYY-MM-DD, отримав {value!r}.") from exc


def _parse_datetime(value: str | None) -> datetime:
    if not value:
        raise ToolError("Потрібен час у форматі YYYY-MM-DD або YYYY-MM-DDTHH:MM.")
    text = str(value).strip()
    try:
        if len(text) == 10:
            parsed = datetime.fromisoformat(text).replace(hour=9)
        else:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ToolError(f"Не зрозумів час {value!r}: чекаю YYYY-MM-DD або YYYY-MM-DDTHH:MM.") from exc
    # Без зони вважаємо, що це час власника, і кладемо як UTC — так само, як
    # робить решта застосунку (розклад за локальним часом сервера).
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _resolve_contact(db: Session, ref) -> Contact:
    """#12, 12 або частина імені. Кілька збігів — просимо уточнити, не вгадуємо."""
    raw = str(ref or "").strip()
    if not raw:
        raise ToolError("Вкажи контакт: #id або частину імені. Знайти: crm_search_contacts.")
    m = _ID_RE.match(raw)
    if m:
        contact = db.get(Contact, int(m.group(1)))
        if contact is None:
            raise ToolError(f"Контакту #{m.group(1)} немає. Знайти: crm_search_contacts.")
        return contact
    needle = raw.casefold()
    matches = [c for c in db.scalars(select(Contact)).unique() if needle in c.full_name.casefold()]
    if not matches:
        raise ToolError(f"Нікого з «{raw}» у назві не знайшов. Спробуй crm_search_contacts.")
    if len(matches) > 1:
        options = ", ".join(f"#{c.id} {c.full_name}" for c in matches[:8])
        raise ToolError(f"Кілька збігів на «{raw}»: {options}. Передай #id.")
    return matches[0]


def _contact_line(c: Contact) -> str:
    from app.modules.interactions import warmth

    role = " · ".join(filter(None, [c.position, c.company]))
    days = int(warmth.days_since_last_contact(c))
    bits = [f"#{c.id} {c.full_name}"]
    if role:
        bits.append(role)
    bits.append(f"{c.warmth_status}, {days} дн без контакту")
    if c.do_not_contact:
        bits.append("стоп-лист")
    if c.auto_reply_paused:
        bits.append("відповідає сам")
    return " — ".join(bits[:2]) + (" · " + " · ".join(bits[2:]) if len(bits) > 2 else "")


# ── Голос власника і памʼять ────────────────────────────────────────────────


def get_owner_voice(db: Session, args: dict) -> str:
    from app import models

    profile = db.get(models.StyleProfile, 1)
    rules = (
        "Правила для будь-якого тексту від імені власника:\n"
        "- мова: та сама, що й у співрозмовника (російською пишуть — російською відповідаємо);\n"
        "- без емодзі;\n"
        "- по суті, без лестощів, без «чудово» і формальних розшаркувань;\n"
        "- у месенджері 1–3 речення, у листі — стільки, скільки треба, і жодного зайвого."
    )
    if profile and profile.summary_md:
        return (
            f"Стиль власника (з {profile.sample_count} його реальних повідомлень):\n"
            f"{profile.summary_md.strip()}\n\n{rules}"
        )
    return (
        "Картка стилю ще не побудована (потрібен імпорт експорту Telegram). "
        "Пиши стримано і по-діловому.\n\n" + rules
    )


def get_contact_memory(db: Session, args: dict) -> str:
    from app.modules.insights.ai import _contact_context

    contact = _resolve_contact(db, args.get("contact"))
    header = _contact_line(contact)
    if contact.tone:
        header += f"\nБажаний тон: {contact.tone}"
    return f"{header}\n\n{_contact_context(contact)}"


def search_contacts(db: Session, args: dict) -> str:
    query = str(args.get("query") or "").strip()
    limit = _int(args.get("limit"), 10, 1, 30)
    if not query:
        raise ToolError("Порожній запит. Передай імʼя, компанію або опис («хто в крипті»).")
    needle = query.casefold()
    rows = [
        c for c in db.scalars(select(Contact)).unique()
        if needle in c.full_name.casefold()
        or needle in (c.company or "").casefold()
        or needle in (c.position or "").casefold()
    ]
    origin = "за назвою/компанією"
    if not rows:
        from app.modules.search import service as search

        ranked = search.semantic_search(db, query, k=limit)
        rows = [db.get(Contact, cid) for cid, _ in ranked]
        rows = [c for c in rows if c]
        origin = "семантично"
    if not rows:
        return f"Нікого не знайшов на «{query}». Якщо це нова людина — її ще немає в базі."
    lines = [f"Знайдено {origin}, {min(len(rows), limit)} з {len(rows)}:"]
    lines += [_contact_line(c) for c in rows[:limit]]
    return "\n".join(lines)


def list_due_contacts(db: Session, args: dict) -> str:
    from app.modules.dashboard import service as dashboard

    limit = _int(args.get("limit"), 10, 1, 30)
    data = dashboard.build_dashboard(db)
    if not data.suggestions:
        return "Ніхто не прострочений — з усіма контакт підтримується."
    lines = [f"Кому пора написати ({min(len(data.suggestions), limit)} з {len(data.suggestions)}):"]
    for s in data.suggestions[:limit]:
        c = db.get(Contact, s.contact.id)
        lines.append(f"{_contact_line(c) if c else s.contact.full_name}\n  привід: {_clip(s.reason, 160)}")
    return "\n".join(lines)


# ── Зберегти готове ─────────────────────────────────────────────────────────


def save_message_draft(db: Session, args: dict) -> str:
    """Дослівно кладе текст як чернетку в Telegram із кнопками «Надіслати/Вручну»."""
    from app.modules.automation import telegram as tg
    from app.modules.telegram_bot import service as bot
    from app.modules.telegram_bot.handlers import _draft_keyboard, _esc
    from app.modules.telegram_bot.models import DraftKind, DraftStatus, TelegramDraft

    contact = _resolve_contact(db, args.get("contact"))
    text = str(args.get("text") or "").strip()
    if not text:
        raise ToolError("Порожній текст. Спершу напиши повідомлення, потім зберігай.")
    if not contact.telegram_chat_id:
        hint = " Є email — crm_save_email_draft." if contact.email else ""
        raise ToolError(
            f"У {contact.full_name} немає Telegram chat id, чернетку в месенджер покласти нема куди.{hint} "
            "Якщо надішлеш сам — зафіксуй через crm_log_interaction."
        )
    connection = bot.get_enabled_connection(db)
    if connection is None:
        raise ToolError(
            "Telegram Business ще не підключений до бота — чернетку показати нема де. "
            "Надішли сам і зафіксуй через crm_log_interaction."
        )
    draft = TelegramDraft(
        contact_id=contact.id,
        chat_id=contact.telegram_chat_id,
        business_connection_id=connection.connection_id,
        kind=DraftKind.outreach,
        incoming_text=str(args.get("reason") or "Чернетка з Claude")[:500],
        draft_text=text,
        status=DraftStatus.pending,
    )
    db.add(draft)
    db.commit()
    db.refresh(draft)

    card = (
        f"✍️ <b>{_esc(contact.full_name)}</b> — чернетка з Claude\n\n{_esc(text)}"
    )
    sent = tg._call(
        "sendMessage",
        chat_id=tg.settings.telegram_chat_id,
        text=card,
        parse_mode="HTML",
        reply_markup=_draft_keyboard(draft.id, True, outreach=True),
    )
    message_id = ((sent or {}).get("result") or {}).get("message_id")
    if message_id:
        bot.set_admin_message(db, draft, int(message_id))
        return f"Збережено дослівно. Картка з кнопкою «Надіслати» вже в Telegram у власника (чернетка #{draft.id})."
    return (
        f"Чернетку #{draft.id} збережено, але картку в Telegram надіслати не вдалося "
        "(бот або чат не налаштовані). Власник побачить її при наступному /queue."
    )


def log_interaction(db: Session, args: dict) -> str:
    from app import crud
    from app.modules.interactions.models import Channel, Direction
    from app.modules.interactions.schemas import InteractionIn

    contact = _resolve_contact(db, args.get("contact"))
    summary = str(args.get("summary") or "").strip()
    if not summary:
        raise ToolError("Потрібен summary: одним реченням, про що була взаємодія.")
    channel = str(args.get("channel") or "message").lower()
    direction = str(args.get("direction") or "outbound").lower()
    channels = {c.value for c in Channel}
    if channel not in channels:
        raise ToolError(f"channel має бути одним із: {', '.join(sorted(channels))}.")
    if direction not in {"inbound", "outbound"}:
        raise ToolError("direction: inbound або outbound.")
    when = _parse_datetime(args["occurred_at"]) if args.get("occurred_at") else None
    payload = InteractionIn(
        channel=Channel(channel), direction=Direction(direction), summary=summary[:2000],
        occurred_at=when,
    )
    crud.add_interaction(db, contact, payload)
    return f"Записав: {contact.full_name}, {channel}/{direction}, {_when(when or datetime.now(timezone.utc))}. Теплота перерахована."


def add_fact(db: Session, args: dict) -> str:
    from app.modules.insights import service as insights
    from app.modules.insights.models import FactType

    contact = _resolve_contact(db, args.get("contact"))
    value = str(args.get("value") or "").strip()
    if not value:
        raise ToolError("Порожній факт.")
    raw_type = str(args.get("fact_type") or "other").lower()
    try:
        fact_type = FactType(raw_type)
    except ValueError:
        raise ToolError(f"fact_type має бути одним із: {', '.join(t.value for t in FactType)}.")
    fact = insights.add_fact(db, contact, fact_type=fact_type, value=value, source="claude")
    return f"Факт про {contact.full_name} збережено (#{fact.id}, {fact_type.value}): {value}"


# ── Пошта ────────────────────────────────────────────────────────────────────


def list_inbox(db: Session, args: dict) -> str:
    from app.modules.inbox import service as inbox

    limit = _int(args.get("limit"), 10, 1, 30)
    rows = inbox.waiting(db, only_needs_reply=not bool(args.get("all")), limit=limit)
    if not rows:
        return "Пошта розібрана — нічого не чекає на відповідь."
    st = inbox.stats(db)
    lines = [f"Чекають відповіді: {st['waiting']} (термінових {st['urgent']}, понад 2 дні {st['stale']})"]
    for t in rows:
        who = t.from_name or t.from_email
        mark = "!" if t.urgency == "high" else "·"
        draft = " ✍ є чернетка" if t.draft_text else ""
        lines.append(f"{mark} #{t.id} {who} — {_clip(t.topic or t.subject, 90)} ({inbox.age_days(t)} дн){draft}")
    return "\n".join(lines)


def _thread(db: Session, ref):
    from app.modules.inbox import service as inbox

    m = _ID_RE.match(str(ref or "").strip())
    thread = inbox.get(db, int(m.group(1))) if m else None
    if thread is None:
        raise ToolError("Такого листа немає. Номери — у crm_list_inbox (#12).")
    return thread


def get_email(db: Session, args: dict) -> str:
    t = _thread(db, args.get("email"))
    lines = [
        f"#{t.id} · {t.subject}",
        f"від {t.from_name or t.from_email} <{t.from_email}> · {_when(t.last_at)} · {t.messages} повід. у треді",
        f"статус: {t.status}; терміновість: {t.urgency}; про що: {t.topic or '—'}",
        "",
        (t.body or t.snippet or "")[:5000],
    ]
    if t.contact_id:
        lines.insert(3, f"контакт: #{t.contact_id} — памʼять: crm_get_contact_memory")
    if t.draft_text:
        lines += ["", "Поточна чернетка:", t.draft_text]
    return "\n".join(lines)


def save_email_draft(db: Session, args: dict) -> str:
    from app.modules.integrations.google import client as google

    t = _thread(db, args.get("email"))
    text = str(args.get("text") or "").strip()
    if not text:
        raise ToolError("Порожній текст листа.")
    t.draft_text = text
    t.drafted_at = datetime.now(timezone.utc)
    t.draft_id = google.create_draft(db, thread_id=t.thread_id, to=t.from_email, subject=t.subject, body=text)
    db.commit()
    where = "і в чернетках Gmail у тому ж тредi" if t.draft_id else "(у Gmail не потрапила — немає скоупу gmail.compose або Google не підключений)"
    return f"Чернетку до листа #{t.id} збережено дослівно {where}. Надіслати: crm_send_email_draft."


def send_email_draft(db: Session, args: dict) -> str:
    from app.modules.inbox import service as inbox

    t = _thread(db, args.get("email"))
    if not t.draft_text:
        raise ToolError(f"У листа #{t.id} немає чернетки. Спершу crm_save_email_draft.")
    if not inbox.send_reply(db, t):
        raise ToolError("Не надіслалося: Google не підключений або Gmail відхилив запит. Лист лишився в черзі.")
    return f"Відповідь на #{t.id} надіслано в той самий тред, лист закрито."


# ── Задачі, цілі, ворота ────────────────────────────────────────────────────


def list_tasks(db: Session, args: dict) -> str:
    from app.modules.tasks import service as tasks
    from app.modules.telegram_bot.handlers import _task_meta

    limit = _int(args.get("limit"), 15, 1, 50)
    rows = tasks.list_tasks(db, include_done=bool(args.get("include_done")))
    if not rows:
        return "Задач немає."
    lines = [f"Задачі в порядку виконання ({min(len(rows), limit)} з {len(rows)}):"]
    for t in rows[:limit]:
        meta = re.sub(r"<[^>]+>", "", _task_meta(t))
        lines.append(f"#{t.uid} {t.title} — {meta}")
    return "\n".join(lines)


def create_task(db: Session, args: dict) -> str:
    from app.modules.tasks import service as tasks
    from app.modules.tasks.schemas import TaskIn

    title = str(args.get("title") or "").strip()
    if not title:
        raise ToolError("Потрібна назва задачі.")
    payload = TaskIn(
        title=title[:300],
        due_date=_parse_date(args.get("due_date")),
        project=(str(args.get("project")).strip() if args.get("project") else None),
        notes=(str(args.get("notes")).strip() if args.get("notes") else None),
        duration_min=_int(args["duration_min"], 0, 1, 1440) or None if args.get("duration_min") else None,
    )
    task = tasks.create_task(db, payload)
    when = f", до {_when(task.due_date)}" if task.due_date else ""
    return f"Задачу створено: #{task.uid} {task.title}{when}. Зʼявиться в Google Календарі при наступному синку."


def complete_task(db: Session, args: dict) -> str:
    from app.modules.tasks import service as tasks
    from app.modules.tasks.models import TaskStatus

    uid = str(args.get("task") or "").strip().lstrip("#")
    task = tasks.get_by_uid(db, uid) if uid else None
    if task is None:
        raise ToolError("Такої задачі немає. Ідентифікатори — у crm_list_tasks (#uid).")
    if task.status == TaskStatus.done:
        return f"#{task.uid} {task.title} уже закрита."
    task.status = TaskStatus.done
    db.commit()
    return f"Закрито: #{task.uid} {task.title}."


def list_goals(db: Session, args: dict) -> str:
    from app.modules.coach import service as coach
    from app.modules.goals import service as goals

    rows = goals.list_goals(db, active=not bool(args.get("all")))
    if not rows:
        return "Активних цілей немає."
    lines = ["Цілі (пріоритет, статус, останній запис коуча):"]
    for g in rows:
        touched = coach.last_touch(g)
        last = f"запис {touched:%d.%m}" if touched else "без записів"
        area = f" [{g.area}]" if g.area else ""
        lines.append(f"#{g.id} {g.title}{area} — {g.priority}, {g.status}, {last}")
    return "\n".join(lines)


def log_goal_progress(db: Session, args: dict) -> str:
    from app.modules.coach import service as coach
    from app.modules.goals.models import Goal, GoalStatus

    m = _ID_RE.match(str(args.get("goal") or "").strip())
    goal = db.get(Goal, int(m.group(1))) if m else None
    if goal is None:
        raise ToolError("Такої цілі немає. Номери — у crm_list_goals (#id).")
    summary = str(args.get("summary") or "").strip()
    if not summary:
        raise ToolError("Потрібен summary: 3–15 слів, що зрушило.")
    goal.coach_notes = coach.append_note(goal.coach_notes, summary)
    changed = ""
    new_status = str(args.get("status") or "").strip().lower()
    if new_status:
        if new_status not in set(GoalStatus):
            raise ToolError(f"status має бути одним із: {', '.join(s.value for s in GoalStatus)}.")
        if new_status != goal.status:
            before = goal.status
            goal.status = new_status
            db.commit()
            coach.log_status_change(db, goal, before, new_status)
            changed = f"; статус {before} → {new_status}"
    db.commit()
    return f"Записав у журнал цілі #{goal.id}: «{summary}»{changed}."


def list_gates(db: Session, args: dict) -> str:
    from app.modules.gates import service as gates

    rows = gates.open_gates(db)
    if not rows:
        return "Відкритих воріт немає."
    return "Ворота (задачі поза кодом):\n" + "\n".join(
        f"#{t.uid} {gates.gate_line(db, t)}" for t in rows
    )


def create_gate(db: Session, args: dict) -> str:
    from app.modules.gates import service as gates

    text = str(args.get("text") or "").strip()
    if not text:
        raise ToolError("Потрібен текст воріт: що саме зробити поза кодом.")
    task = gates.create_gate(db, text=text, goal_hint=args.get("goal"))
    goal = gates.goal_title(db, task)
    return f"Ворота заведено: #{task.uid} {task.title}" + (f" — блокує «{goal}»" if goal else "") + "."


def close_gate(db: Session, args: dict) -> str:
    from app.modules.gates import service as gates

    uid = str(args.get("gate") or "").strip().lstrip("#")
    task = gates.close_gate(db, uid) if uid else None
    if task is None:
        raise ToolError("Таких воріт немає. Ідентифікатори — у crm_list_gates.")
    return f"Ворота закрито: #{task.uid} {task.title}."


# ── Ідеї, посилання, нагадування ────────────────────────────────────────────


def create_idea(db: Session, args: dict) -> str:
    from app.modules.ideas import service as ideas

    body = str(args.get("text") or "").strip()
    if not body:
        raise ToolError("Порожня ідея.")
    idea = ideas.create_idea(db, body, title=(str(args.get("title")).strip() if args.get("title") else None))
    return f"Ідею збережено: #{idea.id} «{idea.title}». Дописати пізніше можна тим самим інструментом з полем idea."


def save_link(db: Session, args: dict) -> str:
    from app.modules.resources import service as resources

    url = str(args.get("url") or "").strip()
    if not url:
        raise ToolError("Потрібен url.")
    existing = resources.find_by_url(db, url)
    if existing:
        return f"Це посилання вже в списку «на потім»: #{existing.id} {existing.title}."
    r = resources.create_resource(db, url=url, note=(str(args.get("note")).strip() if args.get("note") else None))
    return f"Збережено на потім: #{r.id} {r.title} ({r.kind.value})."


def set_reminder(db: Session, args: dict) -> str:
    from app.modules.automation import reminders

    text = str(args.get("text") or "").strip()
    if not text:
        raise ToolError("Потрібен текст нагадування.")
    due = _parse_datetime(args.get("due_at"))
    contact = _resolve_contact(db, args["contact"]) if args.get("contact") else None
    r = reminders.create_reminder(db, contact, text, due)
    who = f" ({contact.full_name})" if contact else ""
    return f"Нагадування #{r.id}{who} на {due.strftime('%d.%m.%Y %H:%M')}: {text}"


# ── Реєстр ───────────────────────────────────────────────────────────────────


def _schema(props: dict, required: list[str] | None = None) -> dict:
    return {
        "type": "object",
        "properties": props,
        "required": required or [],
        "additionalProperties": False,
    }


_CONTACT = {"type": "string", "description": "Контакт: #id або частина імені."}
_LIMIT = {"type": "integer", "description": "Скільки повернути (1–30).", "minimum": 1, "maximum": 30}
_RO = {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}
_WRITE = {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False}

TOOLS: list[dict] = [
    {"name": "crm_get_owner_voice", "title": "Голос власника",
     "description": "Як пише власник: картка стилю з його реальних повідомлень і правила (мова співрозмовника, без емодзі, без лестощів). Читай перед будь-яким текстом від його імені.",
     "inputSchema": _schema({}), "annotations": _RO},
    {"name": "crm_get_contact_memory", "title": "Памʼять про людину",
     "description": "Усе, що система памʼятає про контакт: досьє, сталі факти, теплота стосунку, історія взаємодій, події життя, свіжі дописи в соцмережах, останні репліки.",
     "inputSchema": _schema({"contact": _CONTACT}, ["contact"]), "annotations": _RO},
    {"name": "crm_search_contacts", "title": "Знайти людей",
     "description": "Пошук по імені, компанії, посаді; якщо нічого — семантично за описом («хто в крипті»).",
     "inputSchema": _schema({"query": {"type": "string"}, "limit": _LIMIT}, ["query"]), "annotations": _RO},
    {"name": "crm_list_due_contacts", "title": "Кому пора написати",
     "description": "Люди, з якими давно не було контакту, з приводом для кожного.",
     "inputSchema": _schema({"limit": _LIMIT}), "annotations": _RO},
    {"name": "crm_save_message_draft", "title": "Зберегти чернетку повідомлення",
     "description": "Кладе твій текст ДОСЛІВНО як чернетку в Telegram власника з кнопкою «Надіслати». Система нічого не переписує. Спершу crm_get_owner_voice і crm_get_contact_memory.",
     "inputSchema": _schema({"contact": _CONTACT, "text": {"type": "string"}, "reason": {"type": "string", "description": "Чому зараз, одним рядком (покажеться на картці)."}}, ["contact", "text"]),
     "annotations": _WRITE},
    {"name": "crm_log_interaction", "title": "Зафіксувати взаємодію",
     "description": "Записати, що спілкування відбулось (лист, дзвінок, зустріч, повідомлення). Перераховує теплоту стосунку.",
     "inputSchema": _schema({"contact": _CONTACT, "summary": {"type": "string"},
                             "channel": {"type": "string", "description": "call, message, email, meeting, social, event, other"},
                             "direction": {"type": "string", "description": "outbound (я написав) або inbound"},
                             "occurred_at": {"type": "string", "description": "YYYY-MM-DD або YYYY-MM-DDTHH:MM; порожньо = зараз"}},
                            ["contact", "summary"]), "annotations": _WRITE},
    {"name": "crm_add_fact", "title": "Додати факт про людину",
     "description": "Сталий факт у досьє (роль, роботодавець, місто, інтерес, сімʼя). Новий роботодавець витісняє старий, історія лишається.",
     "inputSchema": _schema({"contact": _CONTACT, "fact_type": {"type": "string", "description": "role, employer, location, interest, family, relationship, preference, other"}, "value": {"type": "string"}}, ["contact", "value"]),
     "annotations": _WRITE},
    {"name": "crm_list_inbox", "title": "Пошта, що чекає",
     "description": "Листи, які чекають відповіді власника: хто, про що, скільки днів, чи є чернетка.",
     "inputSchema": _schema({"limit": _LIMIT, "all": {"type": "boolean", "description": "true — разом із тим, що система не вважає таким, що потребує відповіді"}}), "annotations": _RO},
    {"name": "crm_get_email", "title": "Прочитати лист",
     "description": "Повний текст листа з черги і його поточна чернетка, якщо є.",
     "inputSchema": _schema({"email": {"type": "string", "description": "#id з crm_list_inbox"}}, ["email"]), "annotations": _RO},
    {"name": "crm_save_email_draft", "title": "Зберегти чернетку листа",
     "description": "Кладе твою відповідь ДОСЛІВНО як чернетку до листа — і в чернетки Gmail у той самий тред. Нічого не надсилає.",
     "inputSchema": _schema({"email": {"type": "string"}, "text": {"type": "string"}}, ["email", "text"]), "annotations": _WRITE},
    {"name": "crm_send_email_draft", "title": "Надіслати чернетку листа",
     "description": "НЕЗВОРОТНО надсилає збережену чернетку в той самий тред і закриває лист. Перед викликом покажи текст власнику.",
     "inputSchema": _schema({"email": {"type": "string"}}, ["email"]),
     "annotations": {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": True}},
    {"name": "crm_list_tasks", "title": "Задачі",
     "description": "Задачі в обчисленому порядку виконання, разом із нагадуваннями і воротами.",
     "inputSchema": _schema({"limit": {"type": "integer", "minimum": 1, "maximum": 50}, "include_done": {"type": "boolean"}}), "annotations": _RO},
    {"name": "crm_create_task", "title": "Створити задачу",
     "description": "Нова задача; з датою потрапить у Google Календар.",
     "inputSchema": _schema({"title": {"type": "string"}, "due_date": {"type": "string", "description": "YYYY-MM-DD"}, "project": {"type": "string"}, "notes": {"type": "string"}, "duration_min": {"type": "integer"}}, ["title"]),
     "annotations": _WRITE},
    {"name": "crm_complete_task", "title": "Закрити задачу",
     "description": "Позначити задачу виконаною.",
     "inputSchema": _schema({"task": {"type": "string", "description": "#uid з crm_list_tasks"}}, ["task"]),
     "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}},
    {"name": "crm_list_goals", "title": "Цілі року",
     "description": "Трекер цілей: пріоритет, статус, коли коуч востаннє записував прогрес.",
     "inputSchema": _schema({"all": {"type": "boolean", "description": "true — разом із закритими й перенесеними"}}), "annotations": _RO},
    {"name": "crm_log_goal_progress", "title": "Записати прогрес по цілі",
     "description": "Дописує рядок у журнал цілі (як робить коуч) і за потреби міняє статус: not started, in progress, almost, done, cancelled, postponed to next year, postponed to far future.",
     "inputSchema": _schema({"goal": {"type": "string", "description": "#id з crm_list_goals"}, "summary": {"type": "string", "description": "3–15 слів"}, "status": {"type": "string"}}, ["goal", "summary"]),
     "annotations": _WRITE},
    {"name": "crm_list_gates", "title": "Ворота",
     "description": "Відкриті задачі поза кодом, скільки висять і які цілі блокують.",
     "inputSchema": _schema({}), "annotations": _RO},
    {"name": "crm_create_gate", "title": "Завести ворота",
     "description": "Задача поза кодом (подзвонити, записати, підписати). Одразу летить у Telegram власника.",
     "inputSchema": _schema({"text": {"type": "string"}, "goal": {"type": "string", "description": "Частина назви цілі, яку це блокує"}}, ["text"]),
     "annotations": _WRITE},
    {"name": "crm_close_gate", "title": "Закрити ворота",
     "description": "Позначити ворота зробленими.",
     "inputSchema": _schema({"gate": {"type": "string", "description": "#uid з crm_list_gates"}}, ["gate"]),
     "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}},
    {"name": "crm_create_idea", "title": "Зберегти ідею",
     "description": "Вільний текст будь-якої довжини — в AI-нотатник ідей власника.",
     "inputSchema": _schema({"text": {"type": "string"}, "title": {"type": "string"}}, ["text"]), "annotations": _WRITE},
    {"name": "crm_save_link", "title": "Посилання на потім",
     "description": "Кладе посилання у список перегляду з нотаткою, замість відкритої вкладки.",
     "inputSchema": _schema({"url": {"type": "string"}, "note": {"type": "string"}}, ["url"]), "annotations": _WRITE},
    {"name": "crm_set_reminder", "title": "Поставити нагадування",
     "description": "Нагадування на дату/час, за бажанням привʼязане до людини — спливе в боті.",
     "inputSchema": _schema({"text": {"type": "string"}, "due_at": {"type": "string", "description": "YYYY-MM-DD (о 09:00) або YYYY-MM-DDTHH:MM"}, "contact": _CONTACT}, ["text", "due_at"]),
     "annotations": _WRITE},
]

HANDLERS = {
    "crm_get_owner_voice": get_owner_voice,
    "crm_get_contact_memory": get_contact_memory,
    "crm_search_contacts": search_contacts,
    "crm_list_due_contacts": list_due_contacts,
    "crm_save_message_draft": save_message_draft,
    "crm_log_interaction": log_interaction,
    "crm_add_fact": add_fact,
    "crm_list_inbox": list_inbox,
    "crm_get_email": get_email,
    "crm_save_email_draft": save_email_draft,
    "crm_send_email_draft": send_email_draft,
    "crm_list_tasks": list_tasks,
    "crm_create_task": create_task,
    "crm_complete_task": complete_task,
    "crm_list_goals": list_goals,
    "crm_log_goal_progress": log_goal_progress,
    "crm_list_gates": list_gates,
    "crm_create_gate": create_gate,
    "crm_close_gate": close_gate,
    "crm_create_idea": create_idea,
    "crm_save_link": save_link,
    "crm_set_reminder": set_reminder,
}


def call_tool(db: Session, name: str, arguments: dict | None) -> tuple[str, bool]:
    """(текст, це_помилка). Будь-який виняток інструмента — теж помилка з текстом."""
    handler = HANDLERS.get(name)
    if handler is None:
        return f"Невідомий інструмент {name}. Доступні: {', '.join(HANDLERS)}.", True
    try:
        return handler(db, arguments or {}), False
    except ToolError as exc:
        return str(exc), True
    except Exception as exc:  # інструмент не має валити транспорт
        db.rollback()
        return f"Інструмент {name} впав: {type(exc).__name__}: {exc}", True
