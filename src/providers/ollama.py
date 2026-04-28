"""Ollama – local LLM runtime (OpenAI-compatible endpoint at /v1)."""

from __future__ import annotations

from ..types import ProviderConfig
from .openai_compat import OpenAICompatibleProvider


class OllamaProvider(OpenAICompatibleProvider):
    PROVIDER_NAME = "ollama"
    DEFAULT_BASE_URL = "http://localhost:11434/v1"
    DEFAULT_MODELS = [
        "llama3.3",
        "llama3.2",
        "llama3.1",
        "mistral",
        "qwen2.5",
        "phi3",
        "gemma2",
        "deepseek-r1",
    ]

    def __init__(self, cfg: ProviderConfig):
        # Ollama typically has no API key; normalize to empty string.
        if not cfg.api_key:
            cfg.api_key = "ollama"
        super().__init__(cfg)
