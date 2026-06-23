"""Single-user authentication middleware.

When `APP_PASSWORD` is set, every request must present either:
  * HTTP Basic auth (APP_USERNAME / APP_PASSWORD) — for the web dashboard, or
  * an `X-API-Key` header equal to API_KEY (or APP_PASSWORD) — for service
    callers such as the Chater bridge.

A few paths stay open so the integration keeps working:
  * /api/health                              (uptime checks)
  * /api/integrations/google/callback        (Google redirects the browser here
                                              with a one-time code)

If `APP_PASSWORD` is empty, auth is disabled (local development).
"""

from __future__ import annotations

import base64
import secrets

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from .config import settings

_OPEN_PATHS = {"/api/health", "/api/integrations/google/callback"}


def _eq(a: str | None, b: str | None) -> bool:
    if a is None or b is None:
        return False
    return secrets.compare_digest(a, b)


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if not settings.auth_enabled or request.url.path in _OPEN_PATHS:
            return await call_next(request)

        # Service-to-service: X-API-Key header.
        provided_key = request.headers.get("x-api-key")
        if provided_key and _eq(provided_key, settings.effective_api_key):
            return await call_next(request)

        # Browser / human: HTTP Basic.
        auth = request.headers.get("authorization", "")
        if auth.startswith("Basic "):
            try:
                decoded = base64.b64decode(auth[6:]).decode("utf-8")
                username, _, password = decoded.partition(":")
            except Exception:
                username = password = ""
            if _eq(username, settings.app_username) and _eq(
                password, settings.app_password
            ):
                return await call_next(request)

        # Challenge the browser (shows a login dialog); API clients get JSON.
        return _unauthorized(request)


def _unauthorized(request: Request) -> Response:
    accepts_html = "text/html" in request.headers.get("accept", "")
    headers = {"WWW-Authenticate": 'Basic realm="Networking AI"'}
    if accepts_html:
        return Response(status_code=401, headers=headers, content="Authentication required")
    return JSONResponse(
        {"detail": "Authentication required"}, status_code=401, headers=headers
    )
