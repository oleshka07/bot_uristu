"""API пошти: черга, синк, чернетки, зміна статусу."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status as http
from sqlalchemy.orm import Session

from app.core.database import get_db

from . import service
from .schemas import StatsOut, SyncOut, ThreadOut, ThreadUpdate

router = APIRouter(prefix="/api/inbox", tags=["inbox"])


def _out(thread) -> ThreadOut:
    data = ThreadOut.model_validate(thread)
    data.age_days = service.age_days(thread)
    data.in_gmail = bool(thread.draft_id)
    data.contact_name = thread.contact.full_name if thread.contact else None
    return data


def _thread_or_404(db: Session, thread_pk: int):
    thread = service.get(db, thread_pk)
    if thread is None:
        raise HTTPException(http.HTTP_404_NOT_FOUND, "Thread not found")
    return thread


@router.get("", response_model=list[ThreadOut])
def list_threads(
    all_waiting: bool = Query(default=False, description="Разом із тим, що не потребує відповіді"),
    db: Session = Depends(get_db),
):
    rows = service.waiting(db, only_needs_reply=not all_waiting)
    return [_out(t) for t in rows]


@router.get("/stats", response_model=StatsOut)
def stats(db: Session = Depends(get_db)):
    return service.stats(db)


@router.post("/sync", response_model=SyncOut)
def sync(
    days: int = Query(default=14, ge=1, le=90),
    db: Session = Depends(get_db),
):
    report = service.sync(db, days=days)
    report["classified"] = service.classify_pending(db)
    report["drafted"] = service.draft_pending(db)
    return report


@router.post("/{thread_pk}/draft", response_model=ThreadOut)
def draft(thread_pk: int, db: Session = Depends(get_db)):
    """Складає (або переписує) чернетку і кладе її в Gmail."""
    thread = service.make_draft(db, _thread_or_404(db, thread_pk))
    return _out(thread)


@router.post("/{thread_pk}/send", response_model=ThreadOut)
def send(thread_pk: int, db: Session = Depends(get_db)):
    """Надсилає готову чернетку у той самий тред."""
    thread = _thread_or_404(db, thread_pk)
    if not service.send_reply(db, thread):
        raise HTTPException(
            http.HTTP_502_BAD_GATEWAY,
            "Не вдалося надіслати — немає чернетки або Google не підключений",
        )
    return _out(thread)


@router.patch("/{thread_pk}", response_model=ThreadOut)
def update(thread_pk: int, payload: ThreadUpdate, db: Session = Depends(get_db)):
    thread = service.set_status(db, _thread_or_404(db, thread_pk), payload.status)
    return _out(thread)
