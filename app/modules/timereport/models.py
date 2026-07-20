"""Time-report request signal.

The bot (cloud) can't reach ActivityWatch on the user's PC (localhost only),
so this is a tiny hand-off: the bot writes a 'pending' request when the user
asks for their weekly tracking; the PC agent polls, generates the report
locally, and posts it back to be analysed and delivered.
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, utcnow


class TimeReportStatus(str, enum.Enum):
    pending = "pending"      # requested, waiting for the PC to pick it up
    claimed = "claimed"      # the PC agent is generating the report
    delivered = "delivered"  # report analysed and sent to Telegram


class TimeReportRequest(Base):
    __tablename__ = "time_report_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    period: Mapped[str] = mapped_column(String(20), default="week")
    status: Mapped[TimeReportStatus] = mapped_column(
        Enum(TimeReportStatus), default=TimeReportStatus.pending, index=True
    )
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
