"""Per-user/IP token-bucket rate limiter middleware."""

from __future__ import annotations

import time

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response


class _TokenBucket:
    __slots__ = ("rate", "burst", "tokens", "last_refill")

    def __init__(self, rate: float, burst: int):
        self.rate = rate
        self.burst = burst
        self.tokens = float(burst)
        self.last_refill = time.monotonic()

    def allow(self) -> bool:
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(self.burst, self.tokens + elapsed * self.rate)
        self.last_refill = now
        if self.tokens >= 1.0:
            self.tokens -= 1.0
            return True
        return False


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, requests_per_second: float = 100.0, burst: int = 200):
        super().__init__(app)
        self._rate = requests_per_second
        self._burst = burst
        self._buckets: dict[str, _TokenBucket] = {}

    def _get_bucket(self, key: str) -> _TokenBucket:
        bucket = self._buckets.get(key)
        if bucket is None:
            bucket = _TokenBucket(self._rate, self._burst)
            self._buckets[key] = bucket
        return bucket

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        key = request.headers.get("x-user-id") or (request.client.host if request.client else "unknown")
        bucket = self._get_bucket(key)

        if not bucket.allow():
            return JSONResponse(
                status_code=429,
                content={"error": {"message": "rate limit exceeded", "type": "rate_limit_error", "code": 429}},
                headers={"Retry-After": "1"},
            )

        return await call_next(request)


def rate_limit_middleware(requests_per_second: float = 100.0, burst: int = 200):
    def _factory(app):
        return RateLimitMiddleware(app, requests_per_second=requests_per_second, burst=burst)
    return _factory
