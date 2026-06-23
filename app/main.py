"""FastAPI application entrypoint.

Serves the JSON API under /api and the single-page dashboard from /.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .config import settings
from .database import init_db
from .routers import ai, contacts, dashboard, imports, integrations

logging.basicConfig(level=logging.INFO)

app = FastAPI(
    title="Networking AI",
    description="Personal relationship intelligence — dossiers, warmth scoring "
    "and AI outreach recommendations.",
    version=__version__,
)

from .auth import AuthMiddleware

app.add_middleware(AuthMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    init_db()
    from . import scheduler

    scheduler.start()


@app.on_event("shutdown")
def on_shutdown() -> None:
    from . import scheduler

    scheduler.shutdown()


@app.get("/api/health", tags=["meta"])
def health() -> dict:
    return {
        "status": "ok",
        "version": __version__,
        "ai_enabled": settings.ai_enabled,
    }


# API routers
app.include_router(dashboard.router)
app.include_router(contacts.router)
app.include_router(ai.router)
app.include_router(imports.router)
app.include_router(integrations.router)


# ── Static frontend ──────────────────────────────────────────────────────────
STATIC_DIR = Path(__file__).parent / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")
