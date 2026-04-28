"""Utility functions: token estimation, cost calculation, hashing."""

from __future__ import annotations

import hashlib
import math
import uuid


def generate_request_id() -> str:
    return uuid.uuid4().hex


def estimate_tokens(text: str) -> int:
    """Rough token estimate: words * 1.3."""
    return int(math.ceil(len(text.split()) * 1.3))


# (prompt_cost_per_1k, completion_cost_per_1k)
_MODEL_PRICING: dict[str, tuple[float, float]] = {
    # OpenAI
    "gpt-4o": (0.005, 0.015),
    "gpt-4o-mini": (0.00015, 0.0006),
    "gpt-4-turbo": (0.01, 0.03),
    "gpt-4": (0.03, 0.06),
    "gpt-3.5-turbo": (0.0005, 0.0015),
    # Anthropic
    "claude-3-opus": (0.015, 0.075),
    "claude-3-5-sonnet": (0.003, 0.015),
    "claude-3-sonnet": (0.003, 0.015),
    "claude-3-haiku": (0.00025, 0.00125),
    # Google
    "gemini-1.5-pro": (0.0035, 0.0105),
    "gemini-1.5-flash": (0.00035, 0.00105),
    # Mistral
    "mistral-large-latest": (0.004, 0.012),
    "mistral-medium-latest": (0.0027, 0.0081),
    "mistral-small-latest": (0.001, 0.003),
    # Groq (as of 2025 published rates)
    "llama-3.3-70b-versatile": (0.00059, 0.00079),
    "llama-3.1-70b-versatile": (0.00059, 0.00079),
    "llama-3.1-8b-instant": (0.00005, 0.00008),
    "mixtral-8x7b-32768": (0.00024, 0.00024),
    "gemma2-9b-it": (0.0002, 0.0002),
    # DeepSeek
    "deepseek-chat": (0.00027, 0.0011),
    "deepseek-reasoner": (0.00055, 0.00219),
    # xAI
    "grok-2-latest": (0.002, 0.01),
    "grok-2-1212": (0.002, 0.01),
    "grok-beta": (0.005, 0.015),
    # Perplexity (Sonar)
    "sonar": (0.001, 0.001),
    "sonar-pro": (0.003, 0.015),
    "sonar-reasoning": (0.001, 0.005),
    "sonar-reasoning-pro": (0.002, 0.008),
    # Cohere
    "command-r-plus": (0.0025, 0.01),
    "command-r": (0.00015, 0.0006),
    "command-r-plus-08-2024": (0.0025, 0.01),
    "command-r-08-2024": (0.00015, 0.0006),
    # AI21 Jamba
    "jamba-1.5-large": (0.002, 0.008),
    "jamba-1.5-mini": (0.0002, 0.0004),
    # Together AI (a few headline models)
    "meta-llama/Llama-3.3-70B-Instruct-Turbo": (0.00088, 0.00088),
    "meta-llama/Meta-Llama-3.1-405B-Instruct-Turbo": (0.005, 0.005),
    "deepseek-ai/DeepSeek-V3": (0.00125, 0.00125),
    # Fireworks
    "accounts/fireworks/models/llama-v3p3-70b-instruct": (0.0009, 0.0009),
    "accounts/fireworks/models/mixtral-8x7b-instruct": (0.0005, 0.0005),
    # Ollama / local – zero cost
    "llama3.3": (0.0, 0.0),
    "llama3.1": (0.0, 0.0),
    "mistral": (0.0, 0.0),
    "qwen2.5": (0.0, 0.0),
    "phi3": (0.0, 0.0),
    "gemma2": (0.0, 0.0),
    "deepseek-r1": (0.0, 0.0),
}


def calculate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    pricing = _MODEL_PRICING.get(model, (0.002, 0.006))
    return (prompt_tokens / 1000) * pricing[0] + (completion_tokens / 1000) * pricing[1]


def hash_content(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()
