"""Google integration endpoints: connect, sync, disconnect."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..integrations import google

router = APIRouter(prefix="/api/integrations/google", tags=["integrations"])


@router.get("/status")
def google_status(db: Session = Depends(get_db)):
    return google.status(db)


@router.get("/authorize")
def google_authorize():
    if not settings.google_configured:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Google is not configured. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET.",
        )
    return RedirectResponse(google.build_authorization_url())


@router.get("/callback")
def google_callback(
    code: str | None = None,
    error: str | None = None,
    db: Session = Depends(get_db),
):
    if error:
        return RedirectResponse(f"/?google=error&detail={error}")
    if not code:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Missing authorization code")
    try:
        email = google.handle_oauth_callback(db, code)
    except Exception as exc:
        return RedirectResponse(f"/?google=error&detail={exc}")
    return RedirectResponse(f"/?google=connected&email={email}")


@router.post("/sync")
def google_sync(
    contact_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
):
    report = google.sync(db, contact_id=contact_id)
    return report.as_dict()


@router.post("/disconnect")
def google_disconnect(db: Session = Depends(get_db)):
    google.disconnect(db)
    return {"disconnected": True}
