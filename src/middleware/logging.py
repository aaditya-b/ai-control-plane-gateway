"""Request logging middleware with timing and request-ID injection."""

from __future__ import annotations

import logging
import time
import uuid

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

logger = logging.getLogger("gateway")


class LoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        request.state.request_id = request_id

        start = time.monotonic()
        response = await call_next(request)
        duration_ms = (time.monotonic() - start) * 1000

        response.headers["X-Request-ID"] = request_id

        logger.info(
            "request  method=%s path=%s status=%d duration=%.1fms request_id=%s remote=%s",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
            request_id,
            request.client.host if request.client else "-",
        )

        return response


def logging_middleware(app):
    return LoggingMiddleware(app)
