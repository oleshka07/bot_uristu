"""On-demand PC time-report bridge: request → poll → deliver."""

from app.modules.telegram_bot.handlers import dispatch

from test_telegram_bot import FakeClient


def _cmd(text: str) -> dict:
    return {"update_id": 1, "message": {"chat": {"id": 42}, "text": text}}


def test_time_command_creates_pending_request(client, monkeypatch):
    monkeypatch.setattr(
        "app.core.config.settings.telegram_chat_id", "42", raising=False
    )
    from app.core.database import SessionLocal
    from app.modules.timereport.models import TimeReportRequest, TimeReportStatus
    from sqlalchemy import select

    fake = FakeClient()
    dispatch(fake, _cmd("/time"))
    assert "Запросив трекінг" in fake.sent[-1]["text"]

    with SessionLocal() as db:
        reqs = list(db.scalars(select(TimeReportRequest)))
        assert len(reqs) == 1 and reqs[0].status == TimeReportStatus.pending


def test_nl_trigger_creates_request(client, monkeypatch):
    monkeypatch.setattr(
        "app.core.config.settings.telegram_chat_id", "42", raising=False
    )
    fake = FakeClient()
    dispatch(fake, _cmd("дай трекінг за тиждень"))
    assert "Запросив трекінг" in fake.sent[-1]["text"]


def test_poll_claims_and_deliver_sends(client, monkeypatch):
    from app.modules.timereport import service as tr
    from app.core.database import SessionLocal

    with SessionLocal() as db:
        tr.request_report(db, "week")

    # PC polls → gets the pending request (claimed).
    r = client.get("/api/timereport/poll")
    body = r.json()
    assert body["pending"] is True and body["request_id"]

    # Second poll → nothing pending now.
    assert client.get("/api/timereport/poll").json()["pending"] is False

    # PC delivers the raw report → cloud analyses + sends to Telegram.
    sent = {}
    monkeypatch.setattr(
        "app.modules.automation.telegram.send_message",
        lambda text, **kw: sent.setdefault("msgs", []).append(text) or True,
    )
    # No AI key in tests → analysis is None; raw excerpt still sent.
    resp = client.post(
        "/api/timereport/deliver",
        json={"markdown": "# Тиждень\n- Робота: 20г\n- YouTube: 5г",
              "request_id": body["request_id"]},
    )
    assert resp.json()["ok"] is True
    assert any("YouTube" in m for m in sent.get("msgs", []))

    from app.modules.timereport.models import TimeReportRequest, TimeReportStatus

    with SessionLocal() as db:
        req = db.get(TimeReportRequest, body["request_id"])
        assert req.status == TimeReportStatus.delivered


def test_looks_like_timereport():
    from app.modules.telegram_bot.handlers import _looks_like_timereport

    assert _looks_like_timereport("дай трекінг за тиждень")
    assert _looks_like_timereport("скільки часу я витратив цього тижня")
    assert _looks_like_timereport("статистика по часу")
    assert not _looks_like_timereport("хто з моїх у крипті?")
