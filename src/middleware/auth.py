"""Authentication middleware – validates Bearer tokens against configured API keys."""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response


class AuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, valid_keys: list[str] | None = None):
        super().__init__(app)
        self._key_set: set[str] = set(valid_keys) if valid_keys else set()

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Skip auth if no keys configured
        if not self._key_set:
            return await call_next(request)

        # Skip auth for health/metrics endpoints
        if request.url.path in ("/health", "/metrics"):
            return await call_next(request)

        auth = request.headers.get("authorization", "")
        if not auth:
            return JSONResponse(
                status_code=401,
                content={"error": {"message": "missing Authorization header", "type": "auth_error", "code": 401}},
            )

        token = auth.removeprefix("Bearer ").strip()
        if token not in self._key_set:
            return JSONResponse(
                status_code=401,
                content={"error": {"message": "invalid API key", "type": "auth_error", "code": 401}},
            )

        return await call_next(request)


def auth_middleware(valid_keys: list[str] | None = None):
    """Return a middleware class configured with the given API keys."""
    def _factory(app):
        return AuthMiddleware(app, valid_keys=valid_keys)
    return _factory
