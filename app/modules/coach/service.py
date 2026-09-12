"""Логіка коуча: вибір цілі дня, журнал прогресу, зріз для сторінки.

Сховище одне — наша БД: цілі лежать у ``goals``, журнал у ``goal_checkins``.
Відкрита звірка (рядок без ``answered_at``) водночас є памʼяттю бота про те,
яке питання зараз висить, тож окремого стану тримати не треба.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.goals.models import ACTIVE_STATUSES, Goal, GoalStatus
from app.modules.goals.service import active_goals, list_goals

from .models import CoachSettings, Checkin

logger = logging.getLogger("networking.coach")

#: Скільки годин відкрита звірка ще приймає відповідь.
ANSWER_WINDOW_HOURS = 36

_NOTE_DATE_RE = re.compile(r"\b(\d{2})\.(\d{2})\.(\d{2})\b")


# ── Налаштування ────────────────────────────────────────────────────────────


def get_settings(db: Session) -> CoachSettings:
    """Єдиний рядок налаштувань; створюється при першому зверненні."""
    row = db.get(CoachSettings, 1)
    if row is None:
        row = CoachSettings(id=1)
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


# ── Журнал цілі ─────────────────────────────────────────────────────────────


def note_date(when: datetime | date | None = None) -> str:
    """Дата у форматі журналу — «дд.мм.рр»."""
    when = when or datetime.now()
    return when.strftime("%d.%m.%y")


def append_note(notes: str | None, summary: str, when: datetime | None = None) -> str:
    """Дописує рядок «дд.мм.рр: суть», не затираючи попередні записи."""
    line = f"{note_date(when)}: {' '.join(summary.split())}"
    before = (notes or "").rstrip()
    return f"{before}\n{line}" if before else line


def last_touch(goal: Goal) -> date | None:
    """Остання дата з журналу цілі або ``None``, якщо записів ще не було."""
    best: date | None = None
    for dd, mm, yy in _NOTE_DATE_RE.findall(goal.coach_notes or ""):
        try:
            found = date(2000 + int(yy), int(mm), int(dd))
        except ValueError:
            continue
        if best is None or found > best:
            best = found
    return best


# ── Вибір цілі дня ──────────────────────────────────────────────────────────


def pick_goal(db: Session, *, exclude_ids: set[int] | None = None) -> Goal | None:
    """Ціль, про яку питати сьогодні.

    Спершу ті, яких коуч ще не торкався, далі — найдавніше торкані; за
    рівності виграє вищий пріоритет. Це тримає в полі зору цілі, які інакше
    тихо лежать без руху весь рік.
    """
    skip = exclude_ids or set()
    pool = [g for g in active_goals(db) if g.id not in skip]
    if not pool:
        return None
    pool.sort(
        key=lambda g: (
            last_touch(g) is not None,
            last_touch(g) or date.min,
            -g.priority,
            g.id,
        )
    )
    return pool[0]


def answered_goal_ids(db: Session, on_day: date) -> set[int]:
    """Цілі, на які власник відповів у вказаний день (локальний час)."""
    start = datetime.combine(on_day, datetime.min.time())
    rows = db.scalars(
        select(Checkin).where(
            Checkin.answered_at.is_not(None),
            Checkin.source == "bot",
            Checkin.goal_id.is_not(None),
        )
    ).all()
    end = start + timedelta(days=1)
    out = set()
    for row in rows:
        when = _as_local(row.answered_at)
        if when and start <= when < end:
            out.add(row.goal_id)
    return out


def _as_local(value: datetime | None) -> datetime | None:
    """Зводить збережений UTC-час до наївного локального — час сервера."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value
    return value.astimezone().replace(tzinfo=None)


# ── Відкрита звірка ─────────────────────────────────────────────────────────


def pending_checkin(db: Session) -> Checkin | None:
    """Питання, яке зараз чекає на відповідь (і ще не протухло)."""
    row = db.scalars(
        select(Checkin)
        .where(
            Checkin.answered_at.is_(None),
            Checkin.source == "bot",
            # Питання без тексту ще пише Claude у фоні — на нього не відповідають.
            Checkin.question.is_not(None),
        )
        .order_by(Checkin.asked_at.desc())
        .limit(1)
    ).first()
    if row is None:
        return None
    asked = _as_local(row.asked_at)
    if asked and datetime.now() - asked > timedelta(hours=ANSWER_WINDOW_HOURS):
        return None
    return row


def asked_today(db: Session) -> Checkin | None:
    """Звірка по цілі, створена сьогодні — щоб не питати двічі за день.

    Нагадування по задачах сюди не рахуються: вони живуть за власним
    розкладом і не мають закривати питання дня.
    """
    today = date.today()
    row = db.scalars(
        select(Checkin)
        .where(Checkin.source == "bot", Checkin.goal_id.is_not(None))
        .order_by(Checkin.asked_at.desc())
        .limit(1)
    ).first()
    if row is None:
        return None
    asked = _as_local(row.asked_at)
    return row if asked and asked.date() == today else None


def default_question(goal: Goal) -> str:
    return f"Ціль: {goal.title}. Статус: {goal.status}. Що по ній зараз?"


def open_question(db: Session, *, force: bool = False) -> tuple[Checkin, str] | None:
    """Створює звірку і повертає її разом із текстом питання.

    ``None`` — коли питати нема про що: сьогодні вже питали (і це не ``force``)
    або немає жодної активної цілі. Порожній текст — питання ще пише Claude
    Code у фоні: звірка вже є, надішле її ``set_question_and_send``.
    """
    from app.modules.aijobs import brain

    if not force and asked_today(db) is not None:
        return None

    exclude = answered_goal_ids(db, date.today() - timedelta(days=1))
    goal = pick_goal(db, exclude_ids=exclude)
    if goal is None and exclude:
        # Єдина активна ціль — вчорашня; краще спитати повторно, ніж мовчати.
        goal = pick_goal(db)
    if goal is None:
        return None

    checkin = Checkin(goal_id=goal.id, question=None, status_before=goal.status, kind="progress")
    db.add(checkin)
    db.commit()
    db.refresh(checkin)

    question = brain.coach_question(db, goal, checkin)
    if question is None and brain.deferred():
        return checkin, ""
    question = (question or "").strip() or default_question(goal)
    checkin.question = question
    db.commit()
    return checkin, question


def set_question_and_send(db: Session, checkin: Checkin, text: str) -> bool:
    """Дописує текст питання у звірку (складену у фоні) і надсилає власнику."""
    import html

    from app.modules.automation import telegram

    goal = db.get(Goal, checkin.goal_id) if checkin.goal_id else None
    text = " ".join((text or "").split()) or (default_question(goal) if goal else "Що по цілі?")
    checkin.question = text
    checkin.asked_at = datetime.now(timezone.utc)
    db.commit()
    return telegram.send_message(html.escape(text))


def record_answer(db: Session, answer: str) -> str | None:
    """Розбирає відповідь на відкрите питання і оновлює ціль.

    Повертає текст реакції для власника або ``None``, якщо відкритого
    питання немає — тоді викликач має обробити повідомлення по-своєму.
    """
    checkin = pending_checkin(db)
    if checkin is None:
        return None
    if checkin.task_id is not None:
        return _record_task_answer(db, checkin, answer)
    goal = db.get(Goal, checkin.goal_id)
    checkin.answer = answer
    checkin.answered_at = datetime.now(timezone.utc)
    db.commit()
    if goal is None:
        return "Ціль, про яку було питання, вже видалена."

    from app.modules.aijobs import brain

    review = brain.coach_review(db, goal, checkin, answer)
    if review is None:
        # Claude Code розбере відповідь у фоні і відпише через MCP.
        return "Прийняв, розберу."
    return apply_review(
        db, checkin,
        summary=review.get("summary") or "",
        status=review.get("status") or "",
        reply=review.get("reply") or "",
    )


def apply_review(db: Session, checkin: Checkin, *, summary: str, status: str, reply: str) -> str:
    """Кладе розбір відповіді в журнал цілі. Повертає текст реакції для власника.

    Один вхід для всіх, хто думає: модель через ключ, Claude через MCP, відкат.
    """
    goal = db.get(Goal, checkin.goal_id) if checkin.goal_id else None
    if goal is None:
        return "Ціль, про яку було питання, вже видалена."
    summary = " ".join((summary or "").split())
    if not summary:
        # Без AI (або якщо він мовчить) кладемо в журнал саму відповідь.
        summary = " ".join((checkin.answer or "").split())[:280]

    goal.coach_notes = append_note(goal.coach_notes, summary)
    checkin.summary = summary[:300]

    new_status = (status or "").strip().lower()
    if new_status and new_status in set(GoalStatus) and new_status != goal.status:
        checkin.status_after = new_status
        goal.status = new_status
    if checkin.answered_at is None:
        checkin.answered_at = datetime.now(timezone.utc)
    db.commit()

    reply = " ".join((reply or "").split()) or "Прийняв."
    tail = ["записав"]
    if checkin.status_after:
        tail.append(f"статус -> {checkin.status_after}")
    return f"{reply}\n\n({', '.join(tail)})"


def deliver_review(db: Session, checkin: Checkin, *, summary: str, status: str, reply: str) -> bool:
    """apply_review + надіслати реакцію власнику (для фонового розбору)."""
    import html

    from app.modules.automation import telegram

    text = apply_review(db, checkin, summary=summary, status=status, reply=reply)
    return telegram.send_message(html.escape(text))


def open_task_question(db: Session, task, question: str) -> Checkin:
    """Звірка по задачі-нагадуванню: «що по ній?»."""
    checkin = Checkin(task_id=task.id, question=question, kind="progress")
    db.add(checkin)
    db.commit()
    db.refresh(checkin)
    return checkin


def ask_task_frequency(db: Session, task, question: str) -> Checkin:
    """Уточнення періодичності — окремий вид звірки, з іншою обробкою."""
    checkin = Checkin(task_id=task.id, question=question, kind="frequency")
    db.add(checkin)
    db.commit()
    db.refresh(checkin)
    return checkin


def _record_task_answer(db: Session, checkin: Checkin, answer: str) -> str:
    """Відповідь на нагадування по задачі: періодичність або звіт про роботу."""
    from app.modules.tasks import service as tasks_service
    from app.modules.tasks.models import Task, TaskStatus

    task = db.get(Task, checkin.task_id)
    if task is None:
        checkin.answered_at = datetime.now(timezone.utc)
        checkin.answer = answer
        db.commit()
        return "Задача, про яку було питання, вже видалена."

    checkin.answer = answer
    checkin.answered_at = datetime.now(timezone.utc)

    if checkin.kind == "frequency":
        parsed = tasks_service.parse_recur(answer)
        if parsed is None:
            # Відповідь не про періодичність — питання лишається відкритим.
            checkin.answered_at = None
            db.commit()
            return (
                "Не зрозумів періодичність. Скажи як часто нагадувати: "
                "щодня, раз на тиждень, раз на місяць, раз на квартал."
            )
        recur, days = parsed
        tasks_service.set_recurrence(db, task, recur, days)
        checkin.summary = f"періодичність: {recur}"
        db.commit()
        return (
            f"Нагадуватиму «{task.title}» {recur}. "
            f"Наступне: {task.next_remind_at:%d.%m.%y}."
        )

    low = answer.strip().lower()
    summary = " ".join(answer.split())[:280]
    if low in {"готово", "зробив", "зробила", "done", "виконано", "закрив"}:
        task.status = TaskStatus.done
        task.next_remind_at = None
        checkin.status_after = "done"
        summary = "готово"
    tasks_service.log_reminder_answer(db, task, summary)
    if task.status == TaskStatus.done:
        task.next_remind_at = None
    checkin.summary = summary[:300]
    db.commit()

    if task.status == TaskStatus.done:
        return f"Закрив «{task.title}»."
    when = f" Наступне нагадування: {task.next_remind_at:%d.%m.%y}." if task.next_remind_at else ""
    return f"Записав.{when}"


def mark_nudged(db: Session, checkin: Checkin) -> None:
    checkin.nudges = (checkin.nudges or 0) + 1
    db.commit()


def log_status_change(db: Session, goal: Goal, before: str, after: str) -> None:
    """Фіксує ручну зміну статусу на сторінці — щоб тиждень бачив і її."""
    if before == after:
        return
    now = datetime.now(timezone.utc)
    db.add(
        Checkin(
            goal_id=goal.id,
            asked_at=now,
            answered_at=now,
            source="web",
            status_before=before,
            status_after=after,
            summary=f"статус: {before} -> {after}",
        )
    )
    db.commit()


# ── Зріз для сторінки і тижневого підсумку ──────────────────────────────────


def _bucket(goals: list[Goal]) -> dict:
    counts = {str(s): 0 for s in GoalStatus}
    for g in goals:
        if g.status in counts:
            counts[g.status] += 1
    total = len(goals)
    done = counts[str(GoalStatus.done)]
    closed = done + counts[str(GoalStatus.cancelled)]
    pct = lambda n: round(n * 100 / total) if total else 0  # noqa: E731
    return {
        "total": total,
        "counts": counts,
        "percents": {k: pct(v) for k, v in counts.items()},
        "done": done,
        "done_pct": pct(done),
        # Заголовний відсоток шаблону — «done and cancelled»: питання закрите.
        "closed": closed,
        "closed_pct": pct(closed),
    }


def board(db: Session) -> dict:
    """Три дашборди (Pers, Work, разом) і всі цілі за пріоритетом."""
    goals = list_goals(db)
    goals.sort(key=lambda g: (-g.priority, g.id))
    return {
        "theme": get_settings(db).theme or "",
        "pers": _bucket([g for g in goals if g.area == "pers"]),
        "work": _bucket([g for g in goals if g.area == "work"]),
        "all": _bucket(goals),
        "active": len([g for g in goals if g.status in ACTIVE_STATUSES]),
    }


def week_changes(db: Session, days: int = 7) -> list[Checkin]:
    """Звірки зі зміною статусу за період — і з бота, і зі сторінки."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    return list(
        db.scalars(
            select(Checkin)
            .where(
                Checkin.status_after.is_not(None),
                Checkin.answered_at >= cutoff,
            )
            .order_by(Checkin.answered_at)
        )
    )


def week_entries(db: Session, days: int = 7) -> list[Checkin]:
    """Звірки із записом у журнал за період."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    return list(
        db.scalars(
            select(Checkin)
            .where(
                Checkin.source == "bot",
                Checkin.summary.is_not(None),
                Checkin.answered_at >= cutoff,
            )
            .order_by(Checkin.answered_at)
        )
    )
