"""Projects service: CRUD + пошук-або-створення за назвою (для синхронізації з ПК)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Project, ProjectStatus


def list_projects(db: Session, *, include_done: bool = False) -> list[Project]:
    stmt = select(Project)
    if not include_done:
        stmt = stmt.where(Project.status != ProjectStatus.done)
    return sorted(db.scalars(stmt).unique(), key=lambda p: p.name.lower())


def get_by_name(db: Session, name: str) -> Project | None:
    return db.scalar(select(Project).where(Project.name == name))


def ensure(db: Session, name: str | None) -> Project | None:
    """Назва з focus.md → рядок у БД. Створює, якщо такого проєкту ще нема."""
    name = (name or "").strip()
    if not name:
        return None
    project = get_by_name(db, name)
    if project is None:
        project = Project(name=name)
        db.add(project)
        db.flush()
    return project


def create(db: Session, name: str) -> Project:
    project = ensure(db, name)
    db.commit()
    db.refresh(project)
    return project


def update(db: Session, project: Project, **fields) -> Project:
    for key, value in fields.items():
        if value is not None:
            setattr(project, key, value)
    db.commit()
    db.refresh(project)
    return project


def delete(db: Session, project: Project) -> None:
    """Проєкт зникає, а його задачі й цілі лишаються — просто без проєкту."""
    from app.modules.goals.models import Goal
    from app.modules.tasks.models import Task

    for row in db.scalars(select(Task).where(Task.project_id == project.id)):
        row.project_id, row.project = None, None
    for row in db.scalars(select(Goal).where(Goal.project_id == project.id)):
        row.project_id = None
    db.delete(project)
    db.commit()
