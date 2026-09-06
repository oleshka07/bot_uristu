"""Коуч по цілях: вибір цілі дня, журнал, статуси, зріз для сторінки."""

from datetime import date, datetime, timedelta, timezone


from app.core.database import SessionLocal
from app.modules.coach import service as coach
from app.modules.coach.models import GoalCheckin
from app.modules.goals.models import Goal, GoalStatus


def _goal(db, title, **kw):
    kw.setdefault("status", GoalStatus.in_progress)
    kw.setdefault("priority", 50)
    goal = Goal(title=title, **kw)
    db.add(goal)
    db.commit()
    db.refresh(goal)
    return goal


def test_append_note_keeps_history(client):
    notes = coach.append_note(None, "почав", when=datetime(2026, 5, 1))
    assert notes == "01.05.26: почав"
    notes = coach.append_note(notes, "  дві   книги  ", when=datetime(2026, 5, 3))
    assert notes.splitlines() == ["01.05.26: почав", "03.05.26: дві книги"]


def test_last_touch_takes_newest_entry(client):
    with SessionLocal() as db:
        g = _goal(db, "Книги", coach_notes="01.05.26: а\n03.06.26: б")
        assert coach.last_touch(g) == date(2026, 6, 3)
        assert coach.last_touch(_goal(db, "Без записів")) is None


def test_untouched_goal_is_asked_first(client):
    with SessionLocal() as db:
        _goal(db, "Стара", priority=100, coach_notes="01.05.26: щось")
        _goal(db, "Нова", priority=20)
        assert coach.pick_goal(db).title == "Нова"


def test_then_oldest_touched_then_priority(client):
    with SessionLocal() as db:
        _goal(db, "Свіжа", priority=100, coach_notes="10.05.26: а")
        _goal(db, "Давня", priority=20, coach_notes="01.05.26: б")
        assert coach.pick_goal(db).title == "Давня"

        _goal(db, "Низька", priority=30, coach_notes="01.05.26: в")
        _goal(db, "Висока", priority=90, coach_notes="01.05.26: г")
        # За рівних дат виграє вищий пріоритет.
        assert coach.pick_goal(db).title == "Висока"


def test_closed_goals_are_never_asked(client):
    with SessionLocal() as db:
        _goal(db, "Закрита", status=GoalStatus.done)
        _goal(db, "Скасована", status=GoalStatus.cancelled)
        _goal(db, "Перенесена", status=GoalStatus.postponed_far_future)
        assert coach.pick_goal(db) is None


def test_question_is_asked_once_a_day(client, monkeypatch):
    from app.modules.insights import ai

    monkeypatch.setattr(ai, "coach_question", lambda *a, **kw: "Що по цілі?")
    with SessionLocal() as db:
        _goal(db, "Книги")
        first = coach.open_question(db)
        assert first is not None and first[1] == "Що по цілі?"
        assert coach.open_question(db) is None          # другий раз за день — ні
        assert coach.open_question(db, force=True) is not None  # на вимогу — так


def test_answer_writes_journal_and_moves_status(client, monkeypatch):
    from app.modules.insights import ai

    monkeypatch.setattr(ai, "coach_question", lambda *a, **kw: "Що по книгах?")
    monkeypatch.setattr(
        ai,
        "coach_review",
        lambda *a, **kw: {
            "summary": "прочитав дві книги",
            "status": "almost",
            "reply": "Темп нижчий за план.",
        },
    )
    with SessionLocal() as db:
        goal = _goal(db, "Прочитати 25 книг", status=GoalStatus.not_started)
        coach.open_question(db)
        reply = coach.record_answer(db, "прочитав дві, продовжую")

        db.refresh(goal)
        assert goal.coach_notes.endswith(": прочитав дві книги")
        assert goal.coach_notes.startswith(coach.note_date())
        assert goal.status == "almost"
        assert "статус -> almost" in reply

        checkin = db.query(GoalCheckin).one()
        assert checkin.answered_at is not None
        assert checkin.status_before == "not started"
        assert checkin.status_after == "almost"


def test_invented_status_is_ignored(client, monkeypatch):
    from app.modules.insights import ai

    monkeypatch.setattr(ai, "coach_question", lambda *a, **kw: "?")
    monkeypatch.setattr(
        ai, "coach_review",
        lambda *a, **kw: {"summary": "готово", "status": "виконано", "reply": "ок"},
    )
    with SessionLocal() as db:
        goal = _goal(db, "Ціль", status=GoalStatus.in_progress)
        coach.open_question(db)
        coach.record_answer(db, "готово")
        db.refresh(goal)
        assert goal.status == "in progress"  # вигаданий статус не пройшов


def test_answer_without_open_question_is_not_swallowed(client):
    with SessionLocal() as db:
        _goal(db, "Ціль")
        assert coach.record_answer(db, "просто повідомлення") is None


def test_stale_question_stops_accepting_answers(client, monkeypatch):
    from app.modules.insights import ai

    monkeypatch.setattr(ai, "coach_question", lambda *a, **kw: "?")
    with SessionLocal() as db:
        _goal(db, "Ціль")
        checkin, _ = coach.open_question(db)
        checkin.asked_at = datetime.now(timezone.utc) - timedelta(
            hours=coach.ANSWER_WINDOW_HOURS + 1
        )
        db.commit()
        assert coach.pending_checkin(db) is None


def test_board_counts_pers_work_and_total(client):
    with SessionLocal() as db:
        _goal(db, "P1", area="pers", status=GoalStatus.done)
        _goal(db, "P2", area="pers", status=GoalStatus.cancelled)
        _goal(db, "P3", area="pers", status=GoalStatus.in_progress)
        _goal(db, "W1", area="work", status=GoalStatus.done)
        data = coach.board(db)

    assert data["pers"]["total"] == 3
    assert data["pers"]["done"] == 1
    assert data["pers"]["done_pct"] == 33
    # Заголовний відсоток шаблону — done + cancelled.
    assert data["pers"]["closed"] == 2
    assert data["pers"]["closed_pct"] == 67
    assert data["work"]["total"] == 1
    assert data["all"]["total"] == 4
    assert data["active"] == 1


def test_manual_status_change_lands_in_the_week(client):
    goal = client.post(
        "/api/goals", json={"title": "Ціль", "status": "not started", "priority": 60}
    ).json()
    client.patch(f"/api/goals/{goal['id']}", json={"status": "done"})

    with SessionLocal() as db:
        changes = coach.week_changes(db)
        assert [(c.status_before, c.status_after, c.source) for c in changes] == [
            ("not started", "done", "web")
        ]


def test_weekly_text_calls_a_dead_week_dead(client, monkeypatch):
    from app.modules.insights import ai
    from app.modules.coach import jobs

    monkeypatch.setattr(ai, "coach_week_verdict", lambda *a, **kw: None)
    with SessionLocal() as db:
        _goal(db, "Ціль", area="work")
        text = jobs.weekly_text(db)

    assert "Статуси за тиждень не змінилися" in text
    assert "Записів по жодній цілі за тиждень немає" in text
    assert "Тиждень злитий" in text


def test_board_and_settings_over_api(client):
    assert client.get("/api/coach/board").json()["all"]["total"] == 0

    saved = client.patch(
        "/api/coach/settings",
        json={"theme": "Здоровʼя. Комфорт. Гроші.", "ask_hour": 17},
    ).json()
    assert saved["theme"] == "Здоровʼя. Комфорт. Гроші."
    assert saved["ask_hour"] == 17
    assert client.get("/api/coach/board").json()["theme"] == "Здоровʼя. Комфорт. Гроші."

    # Година поза добою не приймається.
    assert client.patch("/api/coach/settings", json={"ask_hour": 25}).status_code == 422


def test_ask_endpoint_reports_when_there_is_nothing_to_ask(client):
    r = client.post("/api/coach/ask").json()
    assert r["asked"] is False and r["reason"]
