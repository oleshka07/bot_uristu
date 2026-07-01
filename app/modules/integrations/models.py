"""Integration credential storage (shared across integration subpackages)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, utcnow


class IntegrationToken(Base):
    """OAuth credentials for an external integration (e.g. Google).

    Single-user internal tool: one token per provider. Stored as the JSON the
    Google client library serialises (includes the refresh token)."""

    __tablename__ = "integration_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    token_json: Mapped[str] = mapped_column(Text)
    account_email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    last_sync_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
