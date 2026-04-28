"""Together AI – hosted OSS models (OpenAI-compatible)."""

from __future__ import annotations

from .openai_compat import OpenAICompatibleProvider


class TogetherProvider(OpenAICompatibleProvider):
    PROVIDER_NAME = "together"
    DEFAULT_BASE_URL = "https://api.together.xyz/v1"
    DEFAULT_MODELS = [
        "meta-llama/Llama-3.3-70B-Instruct-Turbo",
        "meta-llama/Meta-Llama-3.1-405B-Instruct-Turbo",
        "meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo",
        "meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo",
        "Qwen/Qwen2.5-72B-Instruct-Turbo",
        "deepseek-ai/DeepSeek-V3",
        "mistralai/Mixtral-8x22B-Instruct-v0.1",
    ]
