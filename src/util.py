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
    "gpt-4o": (0.005, 0.015),
    "gpt-4o-mini": (0.00015, 0.0006),
    "gpt-4-turbo": (0.01, 0.03),
    "gpt-4": (0.03, 0.06),
    "gpt-3.5-turbo": (0.0005, 0.0015),
    "claude-3-opus": (0.015, 0.075),
    "claude-3-5-sonnet": (0.003, 0.015),
    "claude-3-sonnet": (0.003, 0.015),
    "claude-3-haiku": (0.00025, 0.00125),
    "gemini-1.5-pro": (0.0035, 0.0105),
    "gemini-1.5-flash": (0.00035, 0.00105),
    "mistral-large-latest": (0.004, 0.012),
    "mistral-medium-latest": (0.0027, 0.0081),
    "mistral-small-latest": (0.001, 0.003),
}


def calculate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    pricing = _MODEL_PRICING.get(model, (0.002, 0.006))
    return (prompt_tokens / 1000) * pricing[0] + (completion_tokens / 1000) * pricing[1]


def hash_content(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()
