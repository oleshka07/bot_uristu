"""Токен доступу до MCP і його облік.

Один токен = один власник (застосунок однокористувацький). Лежить у
``integration_tokens`` під provider="mcp" — та сама таблиця, що й Google,
без нової схеми. Перевипуск замінює значення, стара адреса помирає одразу.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.integrations.models import IntegrationToken

from .protocol import valid_token_format

PROVIDER = "mcp"
#: Позначку «Claude звертався» оновлюємо не частіше разу на 5 хв — інакше
#: кожен виклик інструмента = запис у БД без жодної користі.
SEEN_EVERY = timedelta(minutes=5)


def _row(db: Session) -> IntegrationToken | None:
    return db.scalar(select(IntegrationToken).where(IntegrationToken.provider == PROVIDER))


def current_token(db: Session) -> str | None:
    row = _row(db)
    return row.token_json if row and valid_token_format(row.token_json) else None


def issue_token(db: Session) -> str:
    """Новий токен; попередній перестає діяти цим же коммітом."""
    token = secrets.token_hex(32)
    row = _row(db)
    if row is None:
        row = IntegrationToken(provider=PROVIDER, token_json=token)
        db.add(row)
    else:
        row.token_json = token
        row.last_sync_at = None
    db.commit()
    return token


def revoke_token(db: Session) -> bool:
    row = _row(db)
    if row is None:
        return False
    db.delete(row)
    db.commit()
    return True


def verify(db: Session, presented: str | None) -> bool:
    """Формат — регуляркою до БД; значення — порівнянням сталого часу."""
    if not valid_token_format(presented):
        return False
    expected = current_token(db)
    return bool(expected) and secrets.compare_digest(expected, presented)


def touch_seen(db: Session) -> None:
    row = _row(db)
    if row is None:
        return
    now = datetime.now(timezone.utc)
    last = row.last_sync_at
    if last is not None and last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    if last is None or now - last >= SEEN_EVERY:
        row.last_sync_at = now
        db.commit()


def last_seen(db: Session) -> datetime | None:
    row = _row(db)
    return row.last_sync_at if row else None
