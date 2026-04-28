"""HuggingFace – Inference API / Inference Endpoints.

HuggingFace exposes an OpenAI-compatible chat endpoint via the "Serverless
Inference API with messages" route at
`https://api-inference.huggingface.co/models/{model}/v1/chat/completions`.

The `{model}` path segment is substituted from the request's ``model`` field,
so each call is model-scoped.
"""

from __future__ import annotations

import json
from typing import AsyncIterator

from ..types import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    StreamChunk,
)
from .openai_compat import OpenAICompatibleProvider


class HuggingFaceProvider(OpenAICompatibleProvider):
    PROVIDER_NAME = "huggingface"
    DEFAULT_BASE_URL = "https://api-inference.huggingface.co"
    DEFAULT_MODELS = [
        "meta-llama/Meta-Llama-3.1-70B-Instruct",
        "meta-llama/Meta-Llama-3.1-8B-Instruct",
        "mistralai/Mistral-7B-Instruct-v0.3",
        "mistralai/Mixtral-8x7B-Instruct-v0.1",
        "Qwen/Qwen2.5-72B-Instruct",
        "HuggingFaceH4/zephyr-7b-beta",
    ]

    def _chat_url(self, model: str) -> str:
        return f"{self._base_url}/models/{model}/v1/chat/completions"

    async def chat_completion(
        self, req: ChatCompletionRequest
    ) -> ChatCompletionResponse:
        url = self._chat_url(req.model)
        body = req.model_dump(exclude_none=True)
        body["stream"] = False
        resp = await self._do_with_retries("POST", url, self._headers(), body)
        return self._parse_response(resp.json())

    async def stream_chat_completion(
        self, req: ChatCompletionRequest
    ) -> AsyncIterator[StreamChunk]:
        url = self._chat_url(req.model)
        body = req.model_dump(exclude_none=True)
        body["stream"] = True
        async for raw in self._stream_sse("POST", url, self._headers(), body):
            if raw.strip() == "[DONE]":
                return
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue
            yield self._parse_stream_chunk(data)

    async def health_check(self) -> None:
        # No cheap global health endpoint; probe the default model's metadata.
        if not self._models:
            return
        url = f"{self._base_url}/models/{self._models[0]}"
        await self._do_with_retries("GET", url, self._headers())
