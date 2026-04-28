"""Fireworks AI – hosted OSS models (OpenAI-compatible)."""

from __future__ import annotations

from .openai_compat import OpenAICompatibleProvider


class FireworksProvider(OpenAICompatibleProvider):
    PROVIDER_NAME = "fireworks"
    DEFAULT_BASE_URL = "https://api.fireworks.ai/inference/v1"
    DEFAULT_MODELS = [
        "accounts/fireworks/models/llama-v3p3-70b-instruct",
        "accounts/fireworks/models/llama-v3p1-405b-instruct",
        "accounts/fireworks/models/mixtral-8x22b-instruct",
        "accounts/fireworks/models/deepseek-v3",
        "accounts/fireworks/models/qwen2p5-72b-instruct",
    ]
