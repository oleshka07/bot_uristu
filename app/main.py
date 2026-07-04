"""FastAPI application entrypoint.

Serves the JSON API under /api and the single-page dashboard from /.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import __version__, diagnostics
from .config import settings
from .database import init_db
from .modules.admin.router import router as admin_router
from .modules.contacts.router import router as contacts_router
from .modules.dashboard.router import router as dashboard_router
from .modules.goals.router import router as goals_router
from .modules.insights.router import router as insights_router
from .modules.integrations.router import router as integrations_router
from .modules.integrations.social.router import router as imports_router

logging.basicConfig(level=logging.INFO)
diagnostics.install()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    from .modules.automation import scheduler

    scheduler.start()
    yield
    scheduler.shutdown()


app = FastAPI(
    title="Networking AI",
    description="Personal relationship intelligence — dossiers, warmth scoring "
    "and AI outreach recommendations.",
    version=__version__,
    lifespan=lifespan,
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


@app.get("/api/health", tags=["meta"])
def health() -> dict:
    return {
        "status": "ok",
        "version": __version__,
        "ai_enabled": settings.ai_enabled,
    }


# API routers
app.include_router(dashboard_router)
app.include_router(contacts_router)
app.include_router(insights_router)
app.include_router(imports_router)
app.include_router(integrations_router)
app.include_router(goals_router)
app.include_router(admin_router)


# ── Static frontend ──────────────────────────────────────────────────────────
STATIC_DIR = Path(__file__).parent / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")
