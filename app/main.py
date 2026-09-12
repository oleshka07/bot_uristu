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
from .modules.coach.router import router as coach_router
from .modules.contacts.router import router as contacts_router
from .modules.dashboard.router import router as dashboard_router
from .modules.gates.router import router as gates_router
from .modules.goals.router import router as goals_router
from .modules.insights.router import router as insights_router
from .modules.integrations.router import router as integrations_router
from .modules.integrations.social.monitor_router import router as social_monitor_router
from .modules.integrations.social.router import router as imports_router
from .modules.ideas.router import router as ideas_router
from .modules.inbox.router import router as inbox_router
from .modules.mcp.router import MCPCorsMiddleware, admin_router as mcp_admin_router, router as mcp_router
from .modules.projects.router import router as projects_router
from .modules.resources.router import router as resources_router
from .modules.tasks.router import router as tasks_router
from .modules.timereport.router import router as timereport_router

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

# Додається ПІСЛЯ загального CORS: у Starlette останній доданий — зовнішній,
# тож preflight на /mcp перехоплюємо ми (`*`), а не список дозволених origin-ів.
app.add_middleware(MCPCorsMiddleware)


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
app.include_router(timereport_router)
app.include_router(tasks_router)
app.include_router(projects_router)
app.include_router(ideas_router)
app.include_router(resources_router)
app.include_router(coach_router)
app.include_router(gates_router)
app.include_router(inbox_router)
app.include_router(social_monitor_router)
app.include_router(mcp_router)
app.include_router(mcp_admin_router)


# ── Static frontend ──────────────────────────────────────────────────────────
STATIC_DIR = Path(__file__).parent / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")
