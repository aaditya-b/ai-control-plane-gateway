"""CORS middleware configuration helper."""

from __future__ import annotations

from starlette.middleware.cors import CORSMiddleware


def cors_middleware(app):
    return CORSMiddleware(
        app,
        allow_origins=["*"],
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "X-Request-ID", "X-User-ID", "X-Team-ID"],
        max_age=86400,
    )
