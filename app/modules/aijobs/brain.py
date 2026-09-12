"""Диспетчер «хто думає»: API зараз або задача для Claude Code.

Кожна функція тут — одна фонова потреба. У режимі ``api`` вона робить те, що
робила завжди (викликає модель через ключ і повертає результат). У режимі
``claude_code`` вона ставить задачу в чергу і повертає ``None`` — «відкладено,
результат прийде через MCP-інструмент». Викликачі вміють жити з ``None``.

Так API лишається повноцінним бекендом: вимкнув Claude Code — усе працює,
як до нього. Перейшов на іншого провайдера — теж, це вже шар ``llm``.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.core.config import settings

from . import service as jobs

logger = logging.getLogger("networking.brain")


def mode() -> str:
    value = (settings.background_ai or "api").lower().strip()
    return value if value in {"api", "claude_code", "off"} else "api"


def deferred() -> bool:
    return mode() == "claude_code"


def off() -> bool:
    return mode() == "off"


# ── Вхідне повідомлення в Telegram ──────────────────────────────────────────


def draft_reply(db: Session, draft) -> str | None:
    """Текст чернетки або None (відкладено / вимкнено)."""
    if off():
        return None
    if deferred():
        jobs.enqueue(
            db, "draft_reply", {"draft_id": draft.id},
            dedupe_key=f"draft_reply:{draft.id}",
            delay_seconds=settings.aijobs_debounce_seconds,
        )
        return None
    from app.modules.insights import ai

    return ai.draft_reply(draft.contact, draft.incoming_text or "")


# ── Пошта ────────────────────────────────────────────────────────────────────


def triage_inbox(db: Session) -> dict:
    """У режимі api — класифікує й пише чернетки тут; інакше — одна задача."""
    from app.modules.inbox import service as inbox

    if off():
        return {"classified": 0, "drafted": 0}
    if deferred():
        pending = inbox.untriaged(db, limit=1) or inbox.undrafted(db, limit=1)
        if pending:
            jobs.enqueue(db, "triage_inbox", {}, dedupe_key="triage_inbox")
        return {"classified": 0, "drafted": 0, "deferred": bool(pending)}
    return {"classified": inbox.classify_pending(db), "drafted": inbox.draft_pending(db)}


# ── Памʼять про людей ────────────────────────────────────────────────────────


def consolidate(db: Session, contacts: list) -> dict:
    from app.modules.insights import service as insights

    if off() or not contacts:
        return {"consolidated": 0, "deferred": False}
    if deferred():
        jobs.enqueue(
            db, "consolidate", {"contact_ids": [c.id for c in contacts]},
            dedupe_key="consolidate",
        )
        return {"consolidated": 0, "deferred": True}
    done = facts = failed = 0
    for contact in contacts:
        try:
            result = insights.consolidate_contact(db, contact)
            if result.get("skipped"):
                break
            done += 1
            facts += result.get("facts", 0)
        except Exception as exc:  # pragma: no cover
            db.rollback()
            failed += 1
            logger.warning("consolidation of %s failed: %s", contact.id, exc)
    return {"consolidated": done, "facts": facts, "failed": failed, "deferred": False}


# ── Соцмережі ────────────────────────────────────────────────────────────────


def social_digest(db: Session, contact, new_posts: list) -> dict | None:
    """None = відкладено; тоді дописи лишаються непрочитаними для Claude."""
    if off():
        return {"facts": 0, "hooks": 0}
    if deferred():
        jobs.enqueue(
            db, "social_digest", {"contact_id": contact.id},
            dedupe_key=f"social_digest:{contact.id}",
        )
        return None
    from app.modules.integrations.social import monitor

    return monitor.process_posts_via_api(db, contact, new_posts)


# ── Коуч ─────────────────────────────────────────────────────────────────────


def coach_question(db: Session, goal, checkin) -> str | None:
    """Текст питання або None — тоді питання допише Claude через MCP."""
    if off():
        return None
    if deferred():
        jobs.enqueue(
            db, "coach_question", {"checkin_id": checkin.id},
            dedupe_key=f"coach_question:{checkin.id}",
        )
        return None
    from app.modules.coach import service as coach
    from app.modules.insights import ai

    theme = coach.get_settings(db).theme or ""
    return ai.coach_question(goal.title, goal.status, goal.coach_notes or "", theme)


def coach_review(db: Session, goal, checkin, answer: str) -> dict | None:
    """Розбір відповіді або None — Claude розбере і запише через MCP."""
    if off():
        return {}
    if deferred():
        jobs.enqueue(
            db, "coach_review", {"checkin_id": checkin.id},
            dedupe_key=f"coach_review:{checkin.id}",
        )
        return None
    from app.modules.insights import ai

    return ai.coach_review(goal.title, goal.status, goal.coach_notes or "", answer) or {}


def weekly_verdict(db: Session, block: str, stalled: bool) -> str | None:
    """Вердикт або None — тоді весь підсумок надішле Claude через MCP."""
    if off():
        return ""
    if deferred():
        jobs.enqueue(
            db, "weekly_verdict", {"block": block, "stalled": stalled},
            dedupe_key="weekly_verdict",
        )
        return None
    from app.modules.insights import ai

    return ai.coach_week_verdict(block, stalled) or ""


# ── Відкат: виконати задачу API-шляхом ──────────────────────────────────────


def execute_via_api(db: Session, kind: str, payload: dict) -> str:
    """Той самий результат, що дав би Claude Code, але моделлю через ключ.

    Викликається воркером, коли claude_code вичерпав спроби. Повертає
    короткий звіт для журналу задачі.
    """
    from app.modules.insights import ai

    if kind == "draft_reply":
        from app.modules.telegram_bot import service as bot
        from app.modules.telegram_bot.models import TelegramDraft

        draft = db.get(TelegramDraft, int(payload.get("draft_id") or 0))
        if draft is None:
            return "чернетки вже немає"
        text = ai.draft_reply(draft.contact, draft.incoming_text or "") or ""
        bot.fill_reply_draft(db, draft, text)
        return "чернетку заповнено через API"

    if kind == "triage_inbox":
        from app.modules.inbox import service as inbox

        return f"класифіковано {inbox.classify_pending(db)}, чернеток {inbox.draft_pending(db)}"

    if kind == "consolidate":
        from app.modules.contacts.models import Contact
        from app.modules.insights import service as insights

        done = 0
        for cid in payload.get("contact_ids") or []:
            contact = db.get(Contact, int(cid))
            if contact is not None and not insights.consolidate_contact(db, contact).get("skipped"):
                done += 1
        return f"консолідовано {done}"

    if kind == "social_digest":
        from app.modules.contacts.models import Contact
        from app.modules.integrations.social import monitor

        contact = db.get(Contact, int(payload.get("contact_id") or 0))
        if contact is None:
            return "контакту немає"
        posts = monitor.unprocessed_posts(db, contact)
        r = monitor.process_posts_via_api(db, contact, posts)
        return f"фактів {r['facts']}, приводів {r['hooks']}"

    if kind == "coach_question":
        from app.modules.coach import service as coach
        from app.modules.coach.models import Checkin

        checkin = db.get(Checkin, int(payload.get("checkin_id") or 0))
        if checkin is None or checkin.goal is None:
            return "звірки немає"
        theme = coach.get_settings(db).theme or ""
        goal = checkin.goal
        text = ai.coach_question(goal.title, goal.status, goal.coach_notes or "", theme) \
            or f"Ціль: {goal.title}. Статус: {goal.status}. Що по ній зараз?"
        coach.set_question_and_send(db, checkin, text)
        return "питання надіслано через API"

    if kind == "coach_review":
        from app.modules.coach import service as coach
        from app.modules.coach.models import Checkin

        checkin = db.get(Checkin, int(payload.get("checkin_id") or 0))
        if checkin is None or checkin.goal is None:
            return "звірки немає"
        goal = checkin.goal
        review = ai.coach_review(goal.title, goal.status, goal.coach_notes or "", checkin.answer or "") or {}
        coach.deliver_review(
            db, checkin,
            summary=review.get("summary") or "", status=review.get("status") or "",
            reply=review.get("reply") or "",
        )
        return "відповідь розібрано через API"

    if kind == "weekly_verdict":
        from app.modules.automation import telegram
        from app.modules.coach import jobs as coach_jobs

        block = str(payload.get("block") or "")
        stalled = bool(payload.get("stalled"))
        verdict = ai.coach_week_verdict(block, stalled) or coach_jobs.default_verdict(stalled)
        telegram.send_message(coach_jobs.render_weekly(block, verdict))
        return "тижневий підсумок надіслано через API"

    return f"невідомий вид задачі {kind}"
