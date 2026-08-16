"""Ideas API: capture, grow, list, archive (behind the global X-API-Key)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db

from . import service
from .schemas import IdeaAppend, IdeaIn, IdeaOut, IdeaUpdate

router = APIRouter(prefix="/api/ideas", tags=["ideas"])


def _idea_or_404(db: Session, idea_id: int):
    idea = service.get_idea(db, idea_id)
    if idea is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Idea not found")
    return idea


@router.get("", response_model=list[IdeaOut])
def list_ideas(
    include_archived: bool = Query(default=False),
    db: Session = Depends(get_db),
):
    return service.list_ideas(db, include_archived=include_archived)


@router.post("", response_model=IdeaOut, status_code=status.HTTP_201_CREATED)
def create_idea(payload: IdeaIn, db: Session = Depends(get_db)):
    return service.create_idea(db, body=payload.body, title=payload.title)


@router.get("/{idea_id}", response_model=IdeaOut)
def get_idea(idea_id: int, db: Session = Depends(get_db)):
    return _idea_or_404(db, idea_id)


@router.post("/{idea_id}/append", response_model=IdeaOut)
def append_idea(idea_id: int, payload: IdeaAppend, db: Session = Depends(get_db)):
    return service.append_to_idea(db, _idea_or_404(db, idea_id), payload.text)


@router.patch("/{idea_id}", response_model=IdeaOut)
def update_idea(idea_id: int, payload: IdeaUpdate, db: Session = Depends(get_db)):
    return service.set_status(db, _idea_or_404(db, idea_id), payload.status)


@router.delete("/{idea_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_idea(idea_id: int, db: Session = Depends(get_db)):
    service.delete_idea(db, _idea_or_404(db, idea_id))
