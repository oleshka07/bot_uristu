"""Google integration: OAuth + Gmail/Calendar sync + outbound email.

Turns real emails and calendar meetings with your contacts into interactions,
so relationship warmth reflects reality with zero manual logging.

Single-user tool: one Google account, its token stored in the database
(`integration_tokens`, provider="google"). All Google libraries are imported
lazily so the rest of the app runs even if they're absent.
"""

from __future__ import annotations

import base64
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from email.utils import parseaddr

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import crud, models, warmth
from ..config import settings

logger = logging.getLogger("networking.google")

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/userinfo.email",
    "openid",
]

PROVIDER = "google"


@dataclass
class SyncReport:
    contacts_processed: int = 0
    emails_added: int = 0
    meetings_added: int = 0
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "contacts_processed": self.contacts_processed,
            "emails_added": self.emails_added,
            "meetings_added": self.meetings_added,
            "errors": self.errors,
        }


# ── Token storage ────────────────────────────────────────────────────────────


def _get_token_row(db: Session) -> models.IntegrationToken | None:
    return db.scalar(
        select(models.IntegrationToken).where(
            models.IntegrationToken.provider == PROVIDER
        )
    )


def _save_token(db: Session, token_json: str, account_email: str | None) -> None:
    row = _get_token_row(db)
    if row is None:
        row = models.IntegrationToken(provider=PROVIDER, token_json=token_json)
        db.add(row)
    row.token_json = token_json
    if account_email:
        row.account_email = account_email
    db.commit()


def disconnect(db: Session) -> None:
    row = _get_token_row(db)
    if row:
        db.delete(row)
        db.commit()


def status(db: Session) -> dict:
    row = _get_token_row(db)
    return {
        "configured": settings.google_configured,
        "connected": row is not None,
        "account_email": row.account_email if row else None,
        "last_sync_at": row.last_sync_at.isoformat()
        if row and row.last_sync_at
        else None,
    }


# ── OAuth flow ───────────────────────────────────────────────────────────────


def _client_config() -> dict:
    return {
        "web": {
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [settings.google_redirect_uri],
        }
    }


def build_authorization_url() -> str:
    from google_auth_oauthlib.flow import Flow

    flow = Flow.from_client_config(_client_config(), scopes=SCOPES)
    flow.redirect_uri = settings.google_redirect_uri
    url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",  # force refresh_token on every connect
    )
    return url


def handle_oauth_callback(db: Session, code: str) -> str:
    from google_auth_oauthlib.flow import Flow

    flow = Flow.from_client_config(_client_config(), scopes=SCOPES)
    flow.redirect_uri = settings.google_redirect_uri
    flow.fetch_token(code=code)
    creds = flow.credentials

    account_email = _fetch_account_email(creds)
    _save_token(db, creds.to_json(), account_email)
    return account_email or "(connected)"


# ── Credentials loading ──────────────────────────────────────────────────────


def _load_credentials(db: Session):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    row = _get_token_row(db)
    if row is None:
        return None
    info = json.loads(row.token_json)
    creds = Credentials.from_authorized_user_info(info, SCOPES)
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            _save_token(db, creds.to_json(), row.account_email)
        except Exception as exc:  # pragma: no cover - network/auth
            logger.warning("Google token refresh failed: %s", exc)
            return None
    return creds


def _fetch_account_email(creds) -> str | None:
    try:
        from googleapiclient.discovery import build

        service = build("oauth2", "v2", credentials=creds, cache_discovery=False)
        info = service.userinfo().get().execute()
        return info.get("email")
    except Exception:  # pragma: no cover
        return None


# ── Sync ─────────────────────────────────────────────────────────────────────


def sync(db: Session, contact_id: int | None = None) -> SyncReport:
    """Pull recent Gmail + Calendar activity into interactions.

    If contact_id is given, only that contact is synced; otherwise all
    contacts that have an email address.
    """
    report = SyncReport()
    creds = _load_credentials(db)
    if creds is None:
        report.errors.append("Google account is not connected.")
        return report

    try:
        from googleapiclient.discovery import build

        gmail = build("gmail", "v1", credentials=creds, cache_discovery=False)
        calendar = build("calendar", "v3", credentials=creds, cache_discovery=False)
        my_email = (
            gmail.users().getProfile(userId="me").execute().get("emailAddress", "")
        ).lower()
    except Exception as exc:  # pragma: no cover
        report.errors.append(f"Could not initialise Google services: {exc}")
        return report

    if contact_id is not None:
        contact = db.get(models.Contact, contact_id)
        contacts = [contact] if contact else []
    else:
        contacts = list(db.scalars(select(models.Contact)))

    cutoff = datetime.now(timezone.utc) - timedelta(days=settings.sync_window_days)

    for contact in contacts:
        if not contact or not contact.email:
            continue
        report.contacts_processed += 1
        changed = False
        try:
            changed |= _sync_gmail(db, gmail, contact, my_email, report)
        except Exception as exc:  # pragma: no cover
            report.errors.append(f"Gmail sync failed for {contact.email}: {exc}")
        try:
            changed |= _sync_calendar(db, calendar, contact, cutoff, report)
        except Exception as exc:  # pragma: no cover
            report.errors.append(f"Calendar sync failed for {contact.email}: {exc}")
        if changed:
            db.refresh(contact)
            warmth.refresh(contact)
            db.commit()

    row = _get_token_row(db)
    if row:
        row.last_sync_at = datetime.now(timezone.utc)
        db.commit()
    return report


def _sync_gmail(
    db: Session,
    gmail,
    contact: models.Contact,
    my_email: str,
    report: SyncReport,
) -> bool:
    email = contact.email.lower()
    query = f"(from:{email} OR to:{email}) newer_than:{settings.sync_window_days}d"
    resp = (
        gmail.users()
        .messages()
        .list(userId="me", q=query, maxResults=50)
        .execute()
    )
    messages = resp.get("messages", [])
    added = False
    for ref in messages:
        msg_id = ref["id"]
        external_id = f"gmail:{msg_id}"
        if crud.interaction_exists(db, contact.id, external_id):
            continue
        meta = (
            gmail.users()
            .messages()
            .get(
                userId="me",
                id=msg_id,
                format="metadata",
                metadataHeaders=["From", "To", "Subject", "Date"],
            )
            .execute()
        )
        headers = {
            h["name"].lower(): h["value"]
            for h in meta.get("payload", {}).get("headers", [])
        }
        from_addr = parseaddr(headers.get("from", ""))[1].lower()
        direction = (
            models.Direction.inbound
            if email in from_addr
            else models.Direction.outbound
        )
        occurred_at = _epoch_ms_to_dt(meta.get("internalDate"))
        subject = headers.get("subject", "(no subject)")
        snippet = (meta.get("snippet") or "").strip()
        summary = subject if not snippet else f"{subject} — {snippet[:200]}"
        crud.add_synced_interaction(
            db,
            contact,
            occurred_at=occurred_at,
            channel=models.Channel.email,
            direction=direction,
            summary=summary,
            source="gmail",
            external_id=external_id,
        )
        report.emails_added += 1
        added = True
    return added


def _sync_calendar(
    db: Session,
    calendar,
    contact: models.Contact,
    cutoff: datetime,
    report: SyncReport,
) -> bool:
    email = contact.email.lower()
    now = datetime.now(timezone.utc)
    resp = (
        calendar.events()
        .list(
            calendarId="primary",
            timeMin=cutoff.isoformat(),
            timeMax=now.isoformat(),
            singleEvents=True,
            orderBy="startTime",
            maxResults=250,
        )
        .execute()
    )
    added = False
    for event in resp.get("items", []):
        attendees = event.get("attendees", [])
        attendee_emails = {a.get("email", "").lower() for a in attendees}
        organizer = event.get("organizer", {}).get("email", "").lower()
        if email not in attendee_emails and email != organizer:
            continue
        external_id = f"gcal:{event['id']}"
        if crud.interaction_exists(db, contact.id, external_id):
            continue
        occurred_at = _event_start(event)
        if occurred_at is None or occurred_at > now:
            continue
        summary = event.get("summary", "Meeting")
        crud.add_synced_interaction(
            db,
            contact,
            occurred_at=occurred_at,
            channel=models.Channel.meeting,
            direction=models.Direction.outbound,
            summary=summary,
            source="gcal",
            external_id=external_id,
        )
        report.meetings_added += 1
        added = True
    return added


# ── Outbound email (for the daily digest) ────────────────────────────────────


def send_email(db: Session, to: str, subject: str, body_html: str) -> bool:
    creds = _load_credentials(db)
    if creds is None:
        return False
    try:
        from googleapiclient.discovery import build

        gmail = build("gmail", "v1", credentials=creds, cache_discovery=False)
        message = MIMEText(body_html, "html", "utf-8")
        message["to"] = to
        message["subject"] = subject
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        gmail.users().messages().send(userId="me", body={"raw": raw}).execute()
        return True
    except Exception as exc:  # pragma: no cover
        logger.warning("send_email failed: %s", exc)
        return False


# ── Helpers ──────────────────────────────────────────────────────────────────


def _epoch_ms_to_dt(value) -> datetime:
    try:
        return datetime.fromtimestamp(int(value) / 1000.0, tz=timezone.utc)
    except (TypeError, ValueError):
        return datetime.now(timezone.utc)


def _event_start(event: dict) -> datetime | None:
    start = event.get("start", {})
    raw = start.get("dateTime") or start.get("date")
    if not raw:
        return None
    try:
        if len(raw) == 10:  # all-day date "YYYY-MM-DD"
            return datetime.fromisoformat(raw).replace(tzinfo=timezone.utc)
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
