"""Goals domain service: CRUD, contact links, importance helpers."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.contacts.models import Contact

from .models import Goal, GoalStatus
from .schemas import GoalIn, GoalUpdate


def create_goal(db: Session, payload: GoalIn) -> Goal:
    goal = Goal(**payload.model_dump())
    db.add(goal)
    db.commit()
    db.refresh(goal)
    return goal


def get_goal(db: Session, goal_id: int) -> Goal | None:
    return db.get(Goal, goal_id)


def list_goals(db: Session, *, status: GoalStatus | None = None) -> list[Goal]:
    stmt = select(Goal)
    if status is not None:
        stmt = stmt.where(Goal.status == status)
    goals = list(db.scalars(stmt).unique())
    # Active first, then by priority (high→low), then newest.
    order = {GoalStatus.active: 0, GoalStatus.paused: 1, GoalStatus.done: 2, GoalStatus.dropped: 3}
    goals.sort(key=lambda g: (order.get(g.status, 9), -g.priority, -g.id))
    return goals


def update_goal(db: Session, goal: Goal, payload: GoalUpdate) -> Goal:
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(goal, field, value)
    db.commit()
    db.refresh(goal)
    return goal


def delete_goal(db: Session, goal: Goal) -> None:
    db.delete(goal)
    db.commit()


def link_contact(db: Session, goal: Goal, contact: Contact) -> None:
    if contact not in goal.contacts:
        goal.contacts.append(contact)
        db.commit()


def unlink_contact(db: Session, goal: Goal, contact: Contact) -> None:
    if contact in goal.contacts:
        goal.contacts.remove(contact)
        db.commit()


def active_goals_for_contact(contact: Contact) -> list[Goal]:
    """Active goals this contact is tied to (uses the backref, no query when
    the relationship is already loaded)."""
    return [g for g in getattr(contact, "goals", []) if g.status == GoalStatus.active]


def has_active_goal(contact: Contact) -> bool:
    return bool(active_goals_for_contact(contact))
