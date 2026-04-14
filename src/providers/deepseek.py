"""DeepSeek – DeepSeek-V3 / R1 (OpenAI-compatible)."""

from __future__ import annotations

from .openai_compat import OpenAICompatibleProvider


class DeepSeekProvider(OpenAICompatibleProvider):
    PROVIDER_NAME = "deepseek"
    DEFAULT_BASE_URL = "https://api.deepseek.com/v1"
    DEFAULT_MODELS = [
        "deepseek-chat",      # DeepSeek-V3
        "deepseek-reasoner",  # DeepSeek-R1
    ]
