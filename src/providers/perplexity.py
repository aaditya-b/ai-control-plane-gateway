"""Perplexity – search-grounded LLMs (OpenAI-compatible)."""

from __future__ import annotations

from .openai_compat import OpenAICompatibleProvider


class PerplexityProvider(OpenAICompatibleProvider):
    PROVIDER_NAME = "perplexity"
    DEFAULT_BASE_URL = "https://api.perplexity.ai"
    DEFAULT_MODELS = [
        "sonar",
        "sonar-pro",
        "sonar-reasoning",
        "sonar-reasoning-pro",
    ]
