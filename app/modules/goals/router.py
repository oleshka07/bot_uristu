"""Goals API: CRUD + contact linking."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app import crud
from app.core.database import get_db

from . import service
from .models import GoalStatus
from .schemas import GoalIn, GoalOut, GoalUpdate

router = APIRouter(prefix="/api/goals", tags=["goals"])


def _goal_or_404(db: Session, goal_id: int):
    goal = service.get_goal(db, goal_id)
    if goal is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Goal not found")
    return goal


@router.get("", response_model=list[GoalOut])
def list_goals(
    status_filter: GoalStatus | None = Query(default=None, alias="status"),
    active: bool = Query(default=False, description="Тільки цілі, що в роботі"),
    db: Session = Depends(get_db),
):
    return service.list_goals(db, status=status_filter, active=active)


@router.post("", response_model=GoalOut, status_code=status.HTTP_201_CREATED)
def create_goal(payload: GoalIn, db: Session = Depends(get_db)):
    return service.create_goal(db, payload)


@router.patch("/{goal_id}", response_model=GoalOut)
def update_goal(goal_id: int, payload: GoalUpdate, db: Session = Depends(get_db)):
    from app.modules.coach import service as coach_service

    goal = _goal_or_404(db, goal_id)
    before = goal.status
    updated = service.update_goal(db, goal, payload)
    # Правку статусу руками теж пишемо в журнал — інакше тижневий підсумок
    # бачив би тільки те, що змінив бот.
    coach_service.log_status_change(db, updated, before, updated.status)
    return updated


@router.delete("/{goal_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_goal(goal_id: int, db: Session = Depends(get_db)):
    service.delete_goal(db, _goal_or_404(db, goal_id))


@router.post("/{goal_id}/contacts/{contact_id}", response_model=GoalOut)
def link_contact(goal_id: int, contact_id: int, db: Session = Depends(get_db)):
    goal = _goal_or_404(db, goal_id)
    contact = crud.get_contact(db, contact_id)
    if contact is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Contact not found")
    service.link_contact(db, goal, contact)
    return goal


@router.delete("/{goal_id}/contacts/{contact_id}", response_model=GoalOut)
def unlink_contact(goal_id: int, contact_id: int, db: Session = Depends(get_db)):
    goal = _goal_or_404(db, goal_id)
    contact = crud.get_contact(db, contact_id)
    if contact is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Contact not found")
    service.unlink_contact(db, goal, contact)
    return goal
