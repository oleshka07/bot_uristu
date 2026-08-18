"""Resources API — capture links from anywhere (bookmarklet, extension, bot).

Behind the global X-API-Key, like the rest of /api.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db

from . import service
from .models import ResourceKind, ResourceStatus
from .schemas import ResourceIn, ResourceOut, ResourceUpdate

router = APIRouter(prefix="/api/resources", tags=["resources"])


def _resource_or_404(db: Session, resource_id: int):
    r = service.get_resource(db, resource_id)
    if r is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Resource not found")
    return r


@router.get("", response_model=list[ResourceOut])
def list_resources(
    kind: ResourceKind | None = Query(default=None),
    db: Session = Depends(get_db),
):
    return service.list_open(db, kind=kind)


@router.post("", response_model=ResourceOut, status_code=status.HTTP_201_CREATED)
def create_resource(payload: ResourceIn, db: Session = Depends(get_db)):
    if payload.url:
        existing = service.find_by_url(db, payload.url)
        if existing is not None:
            return existing  # idempotent: same tab saved twice is still one item
    return service.create_resource(
        db,
        url=payload.url,
        note=payload.note,
        title=payload.title,
        kind=payload.kind,
        project_id=payload.project_id,
        idea_id=payload.idea_id,
    )


@router.patch("/{resource_id}", response_model=ResourceOut)
def update_resource(
    resource_id: int, payload: ResourceUpdate, db: Session = Depends(get_db)
):
    r = _resource_or_404(db, resource_id)
    if payload.kind is not None:
        r.kind = payload.kind
    if payload.note is not None:
        r.note = payload.note
    if payload.project_id is not None:
        r.project_id = payload.project_id
    if payload.status is not None:
        return service.set_status(db, r, payload.status)
    db.commit()
    db.refresh(r)
    return r


@router.delete("/{resource_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_resource(resource_id: int, db: Session = Depends(get_db)):
    r = _resource_or_404(db, resource_id)
    db.delete(r)
    db.commit()


@router.get("/stats")
def stats(db: Session = Depends(get_db)):
    items = service.list_open(db)
    by_kind: dict[str, int] = {}
    for r in items:
        by_kind[r.kind.value] = by_kind.get(r.kind.value, 0) + 1
    oldest = max((service.age_days(r) for r in items), default=0)
    return {"open": len(items), "by_kind": by_kind, "oldest_days": oldest}
