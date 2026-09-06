"""Розклад коуча: питання дня, нагадування, тижневий підсумок.

Планувальник будить одну задачу щогодини, а вже вона звіряється з
налаштуваннями в БД. Так години можна міняти на сторінці без перезапуску
контейнера — і без трьох окремих cron-задач, які довелося б перереєстровувати.
"""

from __future__ import annotations

import html
import logging
from datetime import datetime

from app.core.config import settings
from app.core.database import SessionLocal

from . import service

logger = logging.getLogger("networking.coach")


def _esc(s: str) -> str:
    return html.escape(str(s))


def _configured() -> bool:
    return bool(settings.telegram_bot_token and settings.telegram_chat_id)


def send_question(*, force: bool = False) -> bool:
    """Задає питання дня. ``force`` — на вимогу, повз перевірку «вже питали»."""
    if not _configured():
        return False
    from app.modules.automation import telegram

    with SessionLocal() as db:
        opened = service.open_question(db, force=force)
        if opened is None:
            return False
        _, question = opened
    return telegram.send_message(_esc(question))


def send_nudge() -> bool:
    """Колюче нагадування, якщо питання дня висить без відповіді."""
    if not _configured():
        return False
    from app.modules.automation import telegram
    from app.modules.goals.models import Goal
    from app.modules.insights import ai

    with SessionLocal() as db:
        checkin = service.pending_checkin(db)
        if checkin is None or checkin.nudges:
            return False
        goal = db.get(Goal, checkin.goal_id)
        if goal is None:
            return False
        text = ai.coach_nudge(goal.title) or (
            f"Питання про «{goal.title}» висить без відповіді. "
            "Ігнор — теж відповідь, і вона зрозуміла."
        )
        service.mark_nudged(db, checkin)
    return telegram.send_message(_esc(text))


def weekly_text(db) -> str:
    """Тижневий зріз: цифри, зміни статусів, записи — і вердикт."""
    from app.modules.insights import ai

    data = service.board(db)
    changes = service.week_changes(db)
    entries = service.week_entries(db)

    def line(label: str, b: dict) -> str:
        parts = [f"{k}: {v}" for k, v in b["counts"].items() if v]
        head = f"{label}: {b['total']} цілей, done {b['done']} ({b['done_pct']}%)"
        return head + (f"\n  {', '.join(parts)}" if parts else "")

    lines = [f"<b>Тиждень до {datetime.now():%d.%m.%Y}</b>"]
    if data["theme"]:
        lines.append(_esc(data["theme"]))
    lines += ["", line("Pers", data["pers"]), line("Work", data["work"]),
              line("Разом", data["all"]), ""]

    if changes:
        lines.append("Зміни статусів за тиждень:")
        for c in changes:
            title = c.goal.title if c.goal else f"ціль #{c.goal_id}"
            lines.append(f"- {_esc(title)}: {c.status_before} -> {c.status_after}")
    else:
        lines.append("Статуси за тиждень не змінилися.")

    if entries:
        lines += ["", "Записи зʼявилися по цілях:"]
        seen = set()
        for e in entries:
            title = e.goal.title if e.goal else f"ціль #{e.goal_id}"
            if title in seen:
                continue
            seen.add(title)
            lines.append(f"- {_esc(title)}")
    else:
        lines += ["", "Записів по жодній цілі за тиждень немає."]

    stalled = not changes and not entries
    verdict = ai.coach_week_verdict("\n".join(lines), stalled) or (
        "Тиждень злитий: жодного руху по жодній цілі. У понеділок обери одну "
        "ціль і зроби по ній перший крок."
        if stalled
        else "У понеділок візьми одну ціль і зрушь її."
    )
    lines += ["", _esc(verdict)]
    return "\n".join(lines)


def send_weekly() -> bool:
    if not _configured():
        return False
    from app.modules.automation import telegram

    with SessionLocal() as db:
        text = weekly_text(db)
    return telegram.send_message(text)


def run_coach_tick() -> None:
    """Щогодинна задача: сама вирішує, чи зараз час діяти."""
    with SessionLocal() as db:
        cfg = service.get_settings(db)
        enabled = cfg.enabled
        ask_hour, nudge_hour = cfg.ask_hour, cfg.nudge_hour
        weekly_weekday, weekly_hour = cfg.weekly_weekday, cfg.weekly_hour
    if not enabled:
        return

    now = datetime.now()
    try:
        if now.weekday() == weekly_weekday and now.hour == weekly_hour:
            send_weekly()
        if now.hour == ask_hour:
            send_question()
        if now.hour == nudge_hour:
            send_nudge()
    except Exception as exc:  # pragma: no cover - фонова задача не має падати
        logger.warning("coach tick failed: %s", exc)
