"""Транспорт MCP: Streamable HTTP, stateless JSON, токен у шляху.

POST /mcp і /mcp/{token} — JSON-RPC 2.0. GET → 405 (потік сервер→клієнт нам
не потрібен, специфікація дозволяє його не мати). DELETE → 204 (сесій немає).
OPTIONS → 204 + CORS. SSE — лише якщо клієнт не приймає JSON.

Токен у шляху — не лінь: у формі «Add custom connector» на claude.ai є лише
поле URL. Додатково приймаємо Bearer, X-Networking-Token і ?token= для
Claude Code та інспектора.
"""

from __future__ import annotations

import json
import logging
import time
from collections import defaultdict

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, PlainTextResponse

from app.core.config import settings
from app.core.database import SessionLocal, get_db

from . import protocol, service, tools

logger = logging.getLogger("networking.mcp")

router = APIRouter(include_in_schema=False)
admin_router = APIRouter(prefix="/api/integrations/mcp", tags=["mcp"])

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "POST, DELETE, OPTIONS",
    "Access-Control-Allow-Headers": "content-type, authorization, accept, mcp-session-id, mcp-protocol-version, x-networking-token",
    "Access-Control-Expose-Headers": "mcp-protocol-version",
    "Cache-Control": "no-store",
}

#: Рейт-ліміт на IP: 240 запитів за хвилину. У памʼяті процесу — для одного
#: користувача цього досить, а зайвої залежності не треба.
RATE_LIMIT = 240
_hits: dict[str, list[float]] = defaultdict(list)


def _rate_limited(ip: str) -> bool:
    now = time.monotonic()
    window = [t for t in _hits[ip] if now - t < 60]
    window.append(now)
    _hits[ip] = window
    return len(window) > RATE_LIMIT


class MCPCorsMiddleware(BaseHTTPMiddleware):
    """CORS для /mcp окремо від загального: `*`, бо автентифікація не кукою.

    Загальний CORSMiddleware відповідає на preflight за списком дозволених
    origin-ів і повернув би 400 MCP Inspector-у в браузері.
    """

    async def dispatch(self, request: Request, call_next):
        if not request.url.path.startswith("/mcp"):
            return await call_next(request)
        if request.method == "OPTIONS":
            return Response(status_code=204, headers=CORS_HEADERS)
        response = await call_next(request)
        for key, value in CORS_HEADERS.items():
            response.headers[key] = value
        return response


def _presented_token(request: Request, path_token: str | None) -> str | None:
    if path_token:
        return path_token
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    header = request.headers.get("x-networking-token")
    if header:
        return header.strip()
    return request.query_params.get("token")


def _unauthorized() -> JSONResponse:
    body = protocol.rpc_error(
        None, -32001,
        "Невірний або відсутній токен. Візьми свою адресу /mcp/<token> у кабінеті: Integrations → Claude (MCP).",
    )
    return JSONResponse(body, status_code=401, headers=CORS_HEADERS)


def _handle(db: Session, message: dict, client_version_header: str | None) -> dict | None:
    """Одне JSON-RPC повідомлення → відповідь або None для нотифікації."""
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
        return protocol.rpc_error(message.get("id") if isinstance(message, dict) else None, -32600, "Invalid Request")
    method = message.get("method")
    req_id = message.get("id")
    params = message.get("params") or {}

    if protocol.is_notification(message):
        return None
    if method == "initialize":
        requested = params.get("protocolVersion") or client_version_header
        return protocol.rpc_result(req_id, {
            "protocolVersion": protocol.negotiate_version(requested),
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": protocol.SERVER_INFO,
            "instructions": protocol.INSTRUCTIONS,
        })
    if method == "ping":
        return protocol.rpc_result(req_id, {})
    if method == "tools/list":
        return protocol.rpc_result(req_id, {"tools": tools.TOOLS})
    if method == "tools/call":
        name = params.get("name") or ""
        text, failed = tools.call_tool(db, name, params.get("arguments"))
        return protocol.rpc_result(req_id, protocol.tool_fail(text) if failed else protocol.tool_ok(text))
    return protocol.rpc_error(req_id, -32601, f"Method not found: {method}")


async def _post(request: Request, path_token: str | None) -> Response:
    ip = request.client.host if request.client else "?"
    if _rate_limited(ip):
        return JSONResponse(protocol.rpc_error(None, -32029, "Too many requests"), status_code=429, headers=CORS_HEADERS)

    with SessionLocal() as db:
        if not service.verify(db, _presented_token(request, path_token)):
            return _unauthorized()
        try:
            payload = await request.json()
        except Exception:
            return JSONResponse(protocol.rpc_error(None, -32700, "Parse error"), status_code=400, headers=CORS_HEADERS)

        service.touch_seen(db)
        version_header = request.headers.get("mcp-protocol-version")
        messages = payload if isinstance(payload, list) else [payload]
        replies = [r for r in (_handle(db, m, version_header) for m in messages) if r is not None]

    if not replies:
        # Лише нотифікації — 202 з порожнім тілом, як вимагає протокол.
        return Response(status_code=202, headers=CORS_HEADERS)
    body = replies if isinstance(payload, list) else replies[0]

    if protocol.wants_sse(request.headers.get("accept")):
        return PlainTextResponse(
            protocol.sse_frame(body), media_type="text/event-stream", headers=CORS_HEADERS
        )
    return JSONResponse(body, headers=CORS_HEADERS)


@router.post("/mcp")
async def mcp_post(request: Request):
    return await _post(request, None)


@router.post("/mcp/{token}")
async def mcp_post_token(token: str, request: Request):
    return await _post(request, token)


@router.get("/mcp")
@router.get("/mcp/{token}")
async def mcp_get(request: Request, token: str | None = None):
    return Response(status_code=405, headers={**CORS_HEADERS, "Allow": "POST, DELETE, OPTIONS"})


@router.delete("/mcp")
@router.delete("/mcp/{token}")
async def mcp_delete(request: Request, token: str | None = None):
    return Response(status_code=204, headers=CORS_HEADERS)


@router.options("/mcp")
@router.options("/mcp/{token}")
async def mcp_options(request: Request, token: str | None = None):
    return Response(status_code=204, headers=CORS_HEADERS)


# ── Панель у кабінеті (під звичайною авторизацією) ──────────────────────────


class McpStatus(BaseModel):
    configured: bool
    url: str | None = None
    last_seen: str | None = None
    tools: int


def _public_base(request: Request) -> str:
    if settings.public_base_url:
        return settings.public_base_url.rstrip("/")
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
    return f"{proto}://{host}"


def _status(request: Request, db: Session) -> McpStatus:
    token = service.current_token(db)
    seen = service.last_seen(db)
    return McpStatus(
        configured=bool(token),
        url=f"{_public_base(request)}/mcp/{token}" if token else None,
        last_seen=seen.isoformat() if seen else None,
        tools=len(tools.TOOLS),
    )


@admin_router.get("/status", response_model=McpStatus)
def mcp_status(request: Request, db: Session = Depends(get_db)):
    return _status(request, db)


@admin_router.post("/issue", response_model=McpStatus)
def mcp_issue(request: Request, db: Session = Depends(get_db)):
    """Створити або перевипустити адресу. Стара перестає діяти одразу."""
    service.issue_token(db)
    return _status(request, db)


@admin_router.post("/revoke", response_model=McpStatus)
def mcp_revoke(request: Request, db: Session = Depends(get_db)):
    service.revoke_token(db)
    return _status(request, db)
