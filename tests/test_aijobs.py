"""Фоновий AI: черга, диспетчер api/claude_code, воркер, фонові MCP-інструменти.

Головна гарантія — API лишається повноцінним бекендом: у режимі ``api`` все
рахується одразу, як і раніше; у ``claude_code`` задачі стають у чергу, а
результат повертається через MCP-інструменти профілів.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

import pytest

from app.core.config import settings
from app.core.database import SessionLocal
from app.modules.aijobs import brain, prompts, worker
from app.modules.aijobs import service as jobs
from app.modules.aijobs.models import AiJob
from app.modules.contacts.models import Contact
from app.modules.goals.models import Goal, GoalStatus


@pytest.fixture
def claude_mode(monkeypatch):
    monkeypatch.setattr(settings, "background_ai", "claude_code")
    monkeypatch.setattr(settings, "background_ai_fallback", "api")
    monkeypatch.setattr(settings, "aijobs_debounce_seconds", 0)
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "test-token")


@pytest.fixture
def api_mode(monkeypatch):
    monkeypatch.setattr(settings, "background_ai", "api")


@pytest.fixture
def owner_chat(monkeypatch):
    """Telegram «налаштований»: усі виклики Bot API записуються, не летять."""
    from app.modules.automation import telegram

    monkeypatch.setattr(settings, "telegram_bot_token", "t", raising=False)
    monkeypatch.setattr(settings, "telegram_chat_id", "42", raising=False)
    calls = []

    def fake_call(method, **payload):
        calls.append((method, payload))
        return {"ok": True, "result": {"message_id": 100 + len(calls)}}

    monkeypatch.setattr(telegram, "_call", fake_call)
    return calls


@pytest.fixture
def mcp(client):
    status = client.post("/api/integrations/mcp/issue").json()
    token = status["url"].rsplit("/", 1)[-1]

    def rpc(method, params=None, *, profile=None):
        body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
        path = f"/mcp/{token}" + (f"?profile={profile}" if profile else "")
        return client.post(path, json=body)

    def call(name, **arguments):
        r = rpc("tools/call", {"name": name, "arguments": arguments}).json()["result"]
        return r["content"][0]["text"], bool(r.get("isError"))

    return {"rpc": rpc, "call": call}


def _contact(name="Олена", **kw) -> int:
    with SessionLocal() as db:
        c = Contact(first_name=name, **kw)
        db.add(c)
        db.commit()
        return c.id


def _goal(title="Прочитати 25 книг", **kw) -> int:
    with SessionLocal() as db:
        kw.setdefault("status", GoalStatus.in_progress)
        kw.setdefault("priority", 60)
        g = Goal(title=title, **kw)
        db.add(g)
        db.commit()
        return g.id


def _queued(kind: str | None = None) -> list[AiJob]:
    with SessionLocal() as db:
        rows = list(db.query(AiJob).order_by(AiJob.id))
        return [j for j in rows if kind is None or j.kind == kind]


# ── Черга ────────────────────────────────────────────────────────────────────


def test_enqueue_dedupes_while_queued_and_claim_marks_running(client):
    with SessionLocal() as db:
        a = jobs.enqueue(db, "consolidate", {"contact_ids": [1]}, dedupe_key="consolidate")
        b = jobs.enqueue(db, "consolidate", {"contact_ids": [2]}, dedupe_key="consolidate")
        assert a.id == b.id  # друга не заводиться, поки перша чекає
        assert jobs.payload_of(a) == {"contact_ids": [1]}

        job = jobs.claim_next(db)
        assert job.id == a.id and job.status == "running" and job.attempts == 1
        assert jobs.claim_next(db) is None

        # Після виконання той самий ключ знову можна ставити.
        jobs.complete(db, job, backend="claude_code", result="ok", usage={"total_cost_usd": 0.01})
        c = jobs.enqueue(db, "consolidate", {}, dedupe_key="consolidate")
        assert c.id != a.id


def test_debounced_job_is_not_claimable_before_its_time(client):
    with SessionLocal() as db:
        jobs.enqueue(db, "draft_reply", {"draft_id": 1}, delay_seconds=600)
        assert jobs.claim_next(db) is None


def test_fail_retries_until_attempts_run_out(client, monkeypatch):
    monkeypatch.setattr(settings, "aijobs_max_attempts", 2)
    with SessionLocal() as db:
        jobs.enqueue(db, "triage_inbox", {})
        job = jobs.claim_next(db)
        assert jobs.fail(db, job, "boom", retry_in=0) is True
        assert job.status == "queued" and job.error == "boom"
        job = jobs.claim_next(db)
        assert job.attempts == 2
        assert jobs.fail(db, job, "boom again") is False
        assert job.status == "failed"


def test_stale_running_jobs_go_back_to_the_queue(client):
    with SessionLocal() as db:
        jobs.enqueue(db, "triage_inbox", {})
        job = jobs.claim_next(db)
        job.started_at = datetime.now(timezone.utc) - timedelta(hours=1)
        db.commit()
        assert jobs.requeue_stale(db) == 1
        assert db.get(AiJob, job.id).status == "queued"


def test_pause_and_stats(client):
    with SessionLocal() as db:
        assert jobs.is_paused(db) is False
        jobs.set_paused(db, True)
        assert jobs.is_paused(db) is True
        jobs.enqueue(db, "consolidate", {})
        st = jobs.stats(db)
        assert st["paused"] is True and st["counts"]["queued"] == 1


def test_quiet_hours_wrap_midnight(monkeypatch):
    monkeypatch.setattr(settings, "aijobs_quiet_hours", "23-7")
    assert jobs.in_quiet_hours(datetime(2026, 1, 1, 23, 30))
    assert jobs.in_quiet_hours(datetime(2026, 1, 1, 3, 0))
    assert not jobs.in_quiet_hours(datetime(2026, 1, 1, 12, 0))
    monkeypatch.setattr(settings, "aijobs_quiet_hours", "")
    assert not jobs.in_quiet_hours(datetime(2026, 1, 1, 3, 0))


def test_panel_routes(client):
    st = client.get("/api/aijobs/status").json()
    assert st["mode"] == "api" and st["paused"] is False
    assert client.post("/api/aijobs/pause").json()["paused"] is True
    assert client.post("/api/aijobs/resume").json()["paused"] is False
    assert client.get("/api/aijobs").json() == []


# ── Диспетчер: API лишається бекендом ───────────────────────────────────────


def test_api_mode_calls_the_model_immediately(client, api_mode, monkeypatch):
    from app.modules.insights import ai
    from app.modules.telegram_bot.models import DraftKind, TelegramDraft

    monkeypatch.setattr(ai, "draft_reply", lambda contact, text: "Привіт, давай у четвер.")
    cid = _contact()
    with SessionLocal() as db:
        draft = TelegramDraft(contact_id=cid, chat_id=1, kind=DraftKind.reply, incoming_text="Коли?", draft_text="")
        db.add(draft)
        db.commit()
        assert brain.draft_reply(db, draft) == "Привіт, давай у четвер."
    assert _queued() == []


def test_claude_mode_enqueues_instead_of_calling_the_model(client, claude_mode, monkeypatch):
    from app.modules.insights import ai
    from app.modules.telegram_bot.models import DraftKind, TelegramDraft

    def never(*a, **kw):
        raise AssertionError("у режимі claude_code API не має викликатися")

    monkeypatch.setattr(ai, "draft_reply", never)
    cid = _contact()
    with SessionLocal() as db:
        draft = TelegramDraft(contact_id=cid, chat_id=1, kind=DraftKind.reply, incoming_text="Коли?", draft_text="")
        db.add(draft)
        db.commit()
        assert brain.draft_reply(db, draft) is None
        assert brain.draft_reply(db, draft) is None  # дедуп
    rows = _queued("draft_reply")
    assert len(rows) == 1 and rows[0].dedupe_key == f"draft_reply:{rows[0].id and json.loads(rows[0].payload)['draft_id']}"


def test_off_mode_neither_calls_nor_enqueues(client, monkeypatch):
    monkeypatch.setattr(settings, "background_ai", "off")
    with SessionLocal() as db:
        assert brain.triage_inbox(db) == {"classified": 0, "drafted": 0}
        assert brain.weekly_verdict(db, "x", False) == ""
    assert _queued() == []


# ── Вхідне в Telegram: картка без тексту, потім crm_fill_reply_draft ─────────


def test_incoming_message_in_claude_mode_gets_a_placeholder_card_then_text(client, claude_mode, owner_chat, mcp):
    from app.modules.telegram_bot.handlers import dispatch
    from app.modules.telegram_bot.models import DraftStatus, TelegramDraft

    class FakeClient:
        configured = True

        def __init__(self):
            self.sent = []

        def send_message(self, chat_id, text, **kw):
            self.sent.append(text)
            return {"message_id": 777, "chat": {"id": chat_id}}

        def call(self, method, **kw):
            return {}

    fake = FakeClient()
    dispatch(fake, {
        "update_id": 1,
        "business_message": {
            "message_id": 7, "business_connection_id": "bc-1",
            "chat": {"id": 555001, "first_name": "Олег"}, "from": {"id": 555001, "first_name": "Олег"},
            "text": "Привіт! Зустрінемось у четвер?",
        },
    })
    assert fake.sent and "Claude пише чернетку" in fake.sent[0]
    with SessionLocal() as db:
        draft = db.query(TelegramDraft).one()
        assert draft.draft_text == "" and draft.admin_message_id == 777
        draft_id = draft.id
    job = _queued("draft_reply")[0]
    assert json.loads(job.payload) == {"draft_id": draft_id}

    # Воркер (Claude) читає контекст і дописує текст — картка оновлюється.
    text, failed = mcp["call"]("crm_get_pending_reply", draft=f"#{draft_id}")
    assert not failed and "Зустрінемось у четвер" in text and "Памʼять про людину" in text
    text, failed = mcp["call"]("crm_fill_reply_draft", draft=str(draft_id), text="Так, у четвер о 15:00 підходить.")
    assert not failed
    with SessionLocal() as db:
        draft = db.get(TelegramDraft, draft_id)
        assert draft.draft_text == "Так, у четвер о 15:00 підходить."
        assert draft.status == DraftStatus.pending
    edits = [c for c in owner_chat if c[0] == "editMessageText"]
    assert edits and edits[-1][1]["message_id"] == 777 and "15:00" in edits[-1][1]["text"]
    assert edits[-1][1]["reply_markup"]["inline_keyboard"][0][0]["text"].endswith("Надіслати")


def test_skip_from_the_background_closes_the_card(client, claude_mode, owner_chat, mcp):
    from app.modules.telegram_bot.models import DraftKind, DraftStatus, TelegramDraft

    cid = _contact()
    with SessionLocal() as db:
        draft = TelegramDraft(contact_id=cid, chat_id=1, kind=DraftKind.reply, incoming_text="дякую, бувай",
                              draft_text="", admin_message_id=555)
        db.add(draft)
        db.commit()
        draft_id = draft.id
    text, failed = mcp["call"]("crm_fill_reply_draft", draft=str(draft_id), text="[SKIP]")
    assert not failed and "пропущено" in text
    with SessionLocal() as db:
        assert db.get(TelegramDraft, draft_id).status == DraftStatus.skipped
    assert ("deleteMessage", {"chat_id": "42", "message_id": 555}) in owner_chat


def test_reply_profile_lists_only_its_tools(mcp):
    listed = {t["name"] for t in mcp["rpc"]("tools/list", profile="reply").json()["result"]["tools"]}
    assert listed == {"crm_get_pending_reply", "crm_get_owner_voice", "crm_get_contact_memory", "crm_fill_reply_draft"}
    everything = {t["name"] for t in mcp["rpc"]("tools/list").json()["result"]["tools"]}
    assert "crm_fill_reply_draft" not in everything and "crm_save_message_draft" in everything


# ── Пошта ────────────────────────────────────────────────────────────────────


def test_inbox_triage_in_claude_mode_is_one_job_and_tools_do_the_writes(client, claude_mode, mcp, monkeypatch):
    from app.modules.inbox import service as inbox
    from app.modules.inbox.models import EmailThread
    from app.modules.integrations.google import client as google

    monkeypatch.setattr(google, "create_draft", lambda db, **kw: "gmail-draft-1")
    with SessionLocal() as db:
        db.add(EmailThread(thread_id="t1", message_id="m1", subject="Умови співпраці", from_email="maria@example.com",
                           from_name="Марія", snippet="Надішліть умови", body="Надішліть, будь ласка, умови.",
                           last_at=datetime.now(timezone.utc), messages=1))
        db.commit()
        report = brain.triage_inbox(db)
    assert report["deferred"] is True and len(_queued("triage_inbox")) == 1

    text, failed = mcp["call"]("crm_list_untriaged_emails")
    assert not failed and "#1" in text and "Умови співпраці" in text
    text, failed = mcp["call"]("crm_triage_email", email="#1", needs_reply=True, urgency="high", topic="просять умови співпраці")
    assert not failed and "crm_save_email_draft" in text
    text, failed = mcp["call"]("crm_save_email_draft", email="#1", text="Доброго дня, Маріє. Умови у вкладенні.")
    assert not failed
    with SessionLocal() as db:
        t = inbox.get(db, 1)
        assert t.needs_reply is True and t.urgency == "high" and t.topic == "просять умови співпраці"
        assert t.draft_text.startswith("Доброго дня") and t.draft_id == "gmail-draft-1"
        assert inbox.untriaged(db) == [] and inbox.undrafted(db) == []


# ── Памʼять і соцмережі ─────────────────────────────────────────────────────


def test_consolidation_in_claude_mode_queues_contact_ids(client, claude_mode, monkeypatch):
    from app.modules.insights import service as insights

    cid = _contact()
    with SessionLocal() as db:
        contact = db.get(Contact, cid)
        monkeypatch.setattr(insights, "consolidate_contact", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("API")))
        assert brain.consolidate(db, [contact]) == {"consolidated": 0, "deferred": True}
    job = _queued("consolidate")[0]
    assert json.loads(job.payload) == {"contact_ids": [cid]}


def test_dossier_tools_update_memory(client, mcp):
    cid = _contact("Марія")
    words = " ".join(["слово"] * 60)
    text, failed = mcp["call"]("crm_save_dossier", contact=f"#{cid}", text=f"Марія — партнерка. {words}")
    assert not failed
    with SessionLocal() as db:
        c = db.get(Contact, cid)
        assert c.ai_dossier.startswith("Марія") and c.ai_dossier_updated_at is not None
    text, failed = mcp["call"]("crm_save_dossier", contact=f"#{cid}", text="коротко")
    assert failed


def test_social_posts_wait_for_claude_and_tools_close_them(client, claude_mode, mcp, monkeypatch):
    from app.modules.integrations.social import monitor
    from app.modules.integrations.social.models import SocialPost

    cid = _contact("Олена", instagram_url="https://www.instagram.com/olena.k/")
    with SessionLocal() as db:
        contact = db.get(Contact, cid)
        db.add(SocialPost(contact_id=cid, platform="instagram", external_id="p1", url="u",
                          media_type="image", caption="Запустили новий продукт!", posted_at=datetime.now(timezone.utc)))
        db.commit()
        posts = monitor.unprocessed_posts(db, contact)
        assert monitor.process_posts(db, contact, posts) == {"facts": 0, "hooks": 0, "deferred": True}
        assert monitor.unprocessed_posts(db, contact)  # лишилися непрочитаними
    assert len(_queued("social_digest")) == 1

    text, failed = mcp["call"]("crm_list_unprocessed_posts", contact=f"#{cid}")
    assert not failed and "[p1]" in text and "новий продукт" in text
    text, failed = mcp["call"]("crm_add_fact", contact=f"#{cid}", fact_type="role", value="засновниця продукту", post="p1")
    assert not failed
    text, failed = mcp["call"]("crm_add_life_event", contact=f"#{cid}", title="Запуск продукту", event_type="launch", post="p1")
    assert not failed
    text, failed = mcp["call"]("crm_add_life_event", contact=f"#{cid}", title="запуск продукту")
    assert "вже є" in text
    text, failed = mcp["call"]("crm_mark_posts_processed", contact=f"#{cid}")
    assert not failed and "1 дописів" in text
    with SessionLocal() as db:
        c = db.get(Contact, cid)
        assert monitor.unprocessed_posts(db, c) == []
        assert [f.source_ref for f in c.facts] == ["post:p1"]
        assert [e.title for e in c.life_events] == ["Запуск продукту"]


# ── Коуч ─────────────────────────────────────────────────────────────────────


def test_coach_question_is_written_by_claude_and_sent_via_tool(client, claude_mode, owner_chat, mcp):
    from app.modules.coach import jobs as coach_jobs
    from app.modules.coach import service as coach
    from app.modules.coach.models import Checkin

    gid = _goal()
    assert coach_jobs.send_question() is False  # питання ще пише Claude — нічого не летить
    with SessionLocal() as db:
        checkin = db.query(Checkin).one()
        assert checkin.question is None and checkin.goal_id == gid
        assert coach.pending_checkin(db) is None  # на порожнє питання не відповідають
        assert coach.asked_today(db) is not None  # але двічі за день не питаємо
        checkin_id = checkin.id
    assert len(_queued("coach_question")) == 1

    text, failed = mcp["call"]("crm_get_pending_coach_question", checkin=str(checkin_id))
    assert not failed and "Прочитати 25 книг" in text
    text, failed = mcp["call"]("crm_set_coach_question", checkin=str(checkin_id), text="Скільки книг дочитав цього місяця?")
    assert not failed
    sent = [c for c in owner_chat if c[0] == "sendMessage"]
    assert sent and "Скільки книг" in sent[-1][1]["text"]
    with SessionLocal() as db:
        assert coach.pending_checkin(db).question == "Скільки книг дочитав цього місяця?"
    text, failed = mcp["call"]("crm_get_pending_coach_question", checkin=str(checkin_id))
    assert failed  # питання вже є — друге не потрібне


def test_coach_answer_is_reviewed_by_claude_and_recorded_via_tool(client, claude_mode, owner_chat, mcp):
    from app.modules.coach import service as coach
    from app.modules.coach.models import Checkin

    gid = _goal()
    with SessionLocal() as db:
        db.add(Checkin(goal_id=gid, question="Що по книгах?", status_before="in progress"))
        db.commit()
        assert coach.record_answer(db, "дочитав дві, третю почав") == "Прийняв, розберу."
        checkin = db.query(Checkin).one()
        assert checkin.answer and checkin.answered_at and checkin.summary is None
        checkin_id = checkin.id
    assert len(_queued("coach_review")) == 1

    text, failed = mcp["call"]("crm_get_checkin_to_review", checkin=str(checkin_id))
    assert not failed and "дочитав дві" in text
    text, failed = mcp["call"]("crm_record_checkin_review", checkin=str(checkin_id), summary="дві книги, третя в процесі",
                               status="almost", reply="Темп є. Тримай.")
    assert not failed and "almost" in text
    with SessionLocal() as db:
        goal = db.get(Goal, gid)
        assert goal.status == "almost" and "дві книги" in goal.coach_notes
    sent = [c for c in owner_chat if c[0] == "sendMessage"]
    assert "Темп є" in sent[-1][1]["text"]


def test_coach_in_api_mode_still_answers_immediately(client, api_mode, monkeypatch):
    from app.modules.coach import service as coach
    from app.modules.coach.models import Checkin
    from app.modules.insights import ai

    monkeypatch.setattr(ai, "coach_question", lambda *a, **kw: "Що по книгах?")
    monkeypatch.setattr(ai, "coach_review", lambda *a, **kw: {"summary": "дві книги", "status": "almost", "reply": "Мало."})
    gid = _goal()
    with SessionLocal() as db:
        checkin, question = coach.open_question(db)
        assert question == "Що по книгах?" and checkin.question == question
        assert coach.record_answer(db, "дві").startswith("Мало.")
        assert db.get(Goal, gid).status == "almost"
        assert db.query(Checkin).one().summary == "дві книги"
    assert _queued() == []


def test_weekly_summary_is_delegated_and_sent_by_tool(client, claude_mode, owner_chat, mcp):
    from app.modules.coach import jobs as coach_jobs

    _goal()
    assert coach_jobs.send_weekly() is False
    job = _queued("weekly_verdict")[0]
    payload = json.loads(job.payload)
    assert payload["stalled"] is True and "Тиждень до" in payload["block"]

    text, failed = mcp["call"]("crm_get_week_block")
    assert not failed and "БЕЗ РУХУ" in text
    text, failed = mcp["call"]("crm_send_owner_message", text="Тиждень злитий. У понеділок — перший крок по книгах.")
    assert not failed, text
    sent = [c for c in owner_chat if c[0] == "sendMessage"]
    assert "Тиждень злитий" in sent[-1][1]["text"]


# ── Воркер ───────────────────────────────────────────────────────────────────


def test_command_is_locked_down_and_uses_a_profile(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "claude_code_model", "sonnet")
    path = worker.write_mcp_config("http://web:8000/mcp/abc", "reply")
    try:
        cfg = json.load(open(path))
        assert cfg["mcpServers"]["networking"]["url"] == "http://web:8000/mcp/abc?profile=reply"
        cmd = worker.build_command("do it", path)
    finally:
        os.unlink(path)
    assert cmd[:3] == [settings.claude_code_bin, "-p", "do it"]
    assert "--strict-mcp-config" in cmd and "--allowedTools" in cmd
    assert cmd[cmd.index("--model") + 1] == "sonnet"
    banned = cmd[cmd.index("--disallowedTools") + 1]
    assert "Bash" in banned and "Write" in banned  # заборонені вбудовані інструменти
    assert cmd[cmd.index("--allowedTools") + 1] == "mcp__networking"
    assert cmd[-1] == prompts.COMMON


def test_result_parsing_is_tolerant():
    ok = worker.parse_result(json.dumps({"is_error": False, "result": "done", "total_cost_usd": 0.02,
                                         "usage": {"input_tokens": 10, "output_tokens": 5}, "num_turns": 3}))
    assert ok == {"ok": True, "text": "done", "usage": {"total_cost_usd": 0.02, "usage": {"input_tokens": 10, "output_tokens": 5}, "num_turns": 3}}
    assert worker.parse_result(json.dumps({"is_error": True, "result": "limit"}))["ok"] is False
    assert worker.parse_result("")["ok"] is False
    assert worker.parse_result("plain text")["text"] == "plain text"
    assert worker.parse_result('noise\n{"result": "last line"}')["text"] == "last line"


def test_can_run_now_respects_mode_token_pause_and_cap(client, claude_mode, monkeypatch):
    with SessionLocal() as db:
        assert worker.can_run_now(db) == (True, "")
        jobs.set_paused(db, True)
        assert worker.can_run_now(db)[1] == "пауза"
        jobs.set_paused(db, False)
        monkeypatch.setattr(settings, "aijobs_max_per_hour", 1)
        j = jobs.enqueue(db, "triage_inbox", {})
        jobs.claim_next(db)
        jobs.complete(db, j, backend="claude_code", result="", usage={})
        assert worker.can_run_now(db)[1] == "стеля запусків на годину"
        monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN")
        assert worker.can_run_now(db)[1] == "немає CLAUDE_CODE_OAUTH_TOKEN"
        monkeypatch.setattr(settings, "background_ai", "api")
        assert worker.can_run_now(db)[1] == "режим api"


def test_worker_completes_a_job_with_usage(client, claude_mode, monkeypatch):
    seen = {}

    def fake_run(prompt, profile, url):
        seen.update(prompt=prompt, profile=profile, url=url)
        return {"ok": True, "text": "чернетку заповнено", "usage": {"total_cost_usd": 0.03, "usage": {"input_tokens": 100, "output_tokens": 20}}}

    monkeypatch.setattr(worker, "run_claude", fake_run)
    with SessionLocal() as db:
        jobs.enqueue(db, "draft_reply", {"draft_id": 5})
        assert worker.process_one(db) is True
        job = db.query(AiJob).one()
        assert job.status == "done" and job.backend == "claude_code" and job.result == "чернетку заповнено"
        assert jobs.stats(db)["today"] == {"runs": 1, "cost_usd": 0.03, "tokens_in": 100, "tokens_out": 20}
        assert worker.process_one(db) is False
    assert seen["profile"] == "reply" and "#5" in seen["prompt"] and seen["url"].startswith("http://web:8000/mcp/")


def test_worker_falls_back_to_the_api_after_failed_attempts(client, claude_mode, monkeypatch):
    monkeypatch.setattr(settings, "aijobs_max_attempts", 2)
    monkeypatch.setattr(worker, "run_claude", lambda *a: {"ok": False, "text": "claude впав", "usage": {}})
    executed = []
    monkeypatch.setattr(brain, "execute_via_api", lambda db, kind, payload: executed.append((kind, payload)) or "ok через API")
    with SessionLocal() as db:
        jobs.enqueue(db, "triage_inbox", {})
        worker.process_one(db)
        job = db.query(AiJob).one()
        assert job.status == "queued" and job.attempts == 1  # ще одна спроба
        job.run_after = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
        worker.process_one(db)
        db.refresh(job)
        assert job.status == "done" and job.backend == "api" and "відкат на API" in job.result
    assert executed == [("triage_inbox", {})]


def test_without_fallback_the_job_just_fails(client, claude_mode, monkeypatch):
    monkeypatch.setattr(settings, "aijobs_max_attempts", 1)
    monkeypatch.setattr(settings, "background_ai_fallback", "none")
    monkeypatch.setattr(worker, "run_claude", lambda *a: {"ok": False, "text": "ні", "usage": {}})
    with SessionLocal() as db:
        jobs.enqueue(db, "consolidate", {"contact_ids": []})
        worker.process_one(db)
        job = db.query(AiJob).one()
        assert job.status == "failed" and job.backend is None


def test_execute_via_api_covers_every_kind(client, api_mode, monkeypatch, owner_chat):
    """Відкат: той самий результат моделлю через ключ — для всіх семи видів."""
    from app.modules.insights import ai

    monkeypatch.setattr(ai, "coach_week_verdict", lambda *a, **kw: "Вердикт.")
    with SessionLocal() as db:
        assert "API" in brain.execute_via_api(db, "weekly_verdict", {"block": "Тиждень до 01.01.2026\nцифри", "stalled": False})
        assert brain.execute_via_api(db, "draft_reply", {"draft_id": 999}) == "чернетки вже немає"
        assert brain.execute_via_api(db, "social_digest", {"contact_id": 999}) == "контакту немає"
        assert brain.execute_via_api(db, "coach_question", {"checkin_id": 999}) == "звірки немає"
        assert brain.execute_via_api(db, "coach_review", {"checkin_id": 999}) == "звірки немає"
        assert brain.execute_via_api(db, "consolidate", {"contact_ids": []}) == "консолідовано 0"
        assert brain.execute_via_api(db, "triage_inbox", {}).startswith("класифіковано")
    sent = [c for c in owner_chat if c[0] == "sendMessage"]
    assert "<b>Тиждень до 01.01.2026</b>" in sent[-1][1]["text"] and "Вердикт." in sent[-1][1]["text"]


def test_every_kind_has_a_prompt_and_profile():
    for kind in ("draft_reply", "triage_inbox", "consolidate", "social_digest", "coach_question", "coach_review", "weekly_verdict"):
        prompt, profile = prompts.build(kind, {"draft_id": 1, "contact_id": 2, "checkin_id": 3, "stalled": True})
        assert prompt and profile in {"reply", "inbox", "memory", "social", "coach"}
