"""AI21 Labs – Jamba family.

AI21's Studio API is OpenAI-compatible for /chat/completions, so we can
reuse the shared OpenAICompatibleProvider.
"""

from __future__ import annotations

from .openai_compat import OpenAICompatibleProvider


class AI21Provider(OpenAICompatibleProvider):
    PROVIDER_NAME = "ai21"
    DEFAULT_BASE_URL = "https://api.ai21.com/studio/v1"
    DEFAULT_MODELS = [
        "jamba-1.5-large",
        "jamba-1.5-mini",
        "jamba-large",
        "jamba-mini",
    ]
