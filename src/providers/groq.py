"""Groq – ultra-low-latency LPU inference (OpenAI-compatible)."""

from __future__ import annotations

from .openai_compat import OpenAICompatibleProvider


class GroqProvider(OpenAICompatibleProvider):
    PROVIDER_NAME = "groq"
    DEFAULT_BASE_URL = "https://api.groq.com/openai/v1"
    DEFAULT_MODELS = [
        "llama-3.3-70b-versatile",
        "llama-3.1-70b-versatile",
        "llama-3.1-8b-instant",
        "mixtral-8x7b-32768",
        "gemma2-9b-it",
    ]
