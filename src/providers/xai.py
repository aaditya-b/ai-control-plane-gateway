"""xAI – Grok models (OpenAI-compatible)."""

from __future__ import annotations

from .openai_compat import OpenAICompatibleProvider


class XAIProvider(OpenAICompatibleProvider):
    PROVIDER_NAME = "xai"
    DEFAULT_BASE_URL = "https://api.x.ai/v1"
    DEFAULT_MODELS = [
        "grok-2-latest",
        "grok-2-1212",
        "grok-beta",
    ]
