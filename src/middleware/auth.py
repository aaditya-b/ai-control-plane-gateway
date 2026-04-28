"""Authentication middleware — static Bearer token validation."""

from __future__ import annotations

import logging

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

logger = logging.getLogger("gateway.auth")

# Paths that skip authentication entirely
_OPEN_PATHS = {"/health", "/metrics", "/docs", "/openapi.json"}


class AuthMiddleware(BaseHTTPMiddleware):
    """
    Validates Bearer tokens against a static set of configured API keys.

    If no keys are configured the middleware is a no-op (open / dev mode).
    """

    def __init__(self, app, valid_keys: list[str] | None = None):
        super().__init__(app)
        self._key_set: set[str] = set(valid_keys) if valid_keys else set()

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Always allow open endpoints
        if request.url.path in _OPEN_PATHS:
            return await call_next(request)

        # No keys configured — open (dev mode)
        if not self._key_set:
            return await call_next(request)

        auth = request.headers.get("authorization", "")
        if not auth:
            return _auth_error("missing Authorization header")

        token = auth.removeprefix("Bearer ").strip()
        if not token:
            return _auth_error("empty Bearer token")

        if token not in self._key_set:
            logger.warning("invalid API key attempt from %s", request.client)
            return _auth_error("invalid API key")

        request.state.auth_principal = f"api_key:{token[:8]}…"
        return await call_next(request)


def _auth_error(message: str, status_code: int = 401) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "message": message,
                "type": "auth_error",
                "code": status_code,
            }
        },
    )


def auth_middleware(valid_keys: list[str] | None = None):
    """Return a configured auth middleware factory for use with app.add_middleware()."""
    def _factory(app):
        return AuthMiddleware(app, valid_keys=valid_keys)
    return _factory
