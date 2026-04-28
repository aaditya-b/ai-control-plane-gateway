"""OpenAI-compatible base adapter.

Many providers (Groq, Together, DeepSeek, xAI, Perplexity, Fireworks, Ollama,
etc.) expose a `/chat/completions` endpoint that exactly matches the OpenAI
schema. This base class captures that shared behavior so each adapter only
needs to supply a name, default base URL, and default models.
"""

from __future__ import annotations

import json
from typing import AsyncIterator

from ..types import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    Choice,
    Message,
    ProviderConfig,
    StreamChoice,
    StreamChunk,
    Usage,
)
from .base import BaseProvider


class OpenAICompatibleProvider(BaseProvider):
    """Shared implementation for OpenAI-compatible providers."""

    #: Override in subclasses
    DEFAULT_BASE_URL: str = ""
    DEFAULT_MODELS: list[str] = []
    PROVIDER_NAME: str = "openai-compatible"

    def __init__(self, cfg: ProviderConfig):
        if not cfg.base_url:
            cfg.base_url = self.DEFAULT_BASE_URL
        if not cfg.models:
            cfg.models = list(self.DEFAULT_MODELS)
        super().__init__(cfg)

    def name(self) -> str:
        return self.PROVIDER_NAME

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    async def chat_completion(
        self, req: ChatCompletionRequest
    ) -> ChatCompletionResponse:
        url = f"{self._base_url}/chat/completions"
        body = req.model_dump(exclude_none=True)
        body["stream"] = False

        resp = await self._do_with_retries("POST", url, self._headers(), body)
        data = resp.json()
        return self._parse_response(data)

    async def stream_chat_completion(
        self, req: ChatCompletionRequest
    ) -> AsyncIterator[StreamChunk]:
        url = f"{self._base_url}/chat/completions"
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
        # Most OpenAI-compatible providers expose /models
        url = f"{self._base_url}/models"
        await self._do_with_retries("GET", url, self._headers())

    @staticmethod
    def _parse_response(data: dict) -> ChatCompletionResponse:
        choices: list[Choice] = []
        for c in data.get("choices", []):
            msg = c.get("message", {})
            choices.append(
                Choice(
                    index=c.get("index", 0),
                    message=Message(
                        role=msg.get("role", "assistant"),
                        content=msg.get("content", "") or "",
                    ),
                    finish_reason=c.get("finish_reason", "stop"),
                )
            )
        u = data.get("usage", {}) or {}
        usage = Usage(
            prompt_tokens=u.get("prompt_tokens", 0),
            completion_tokens=u.get("completion_tokens", 0),
            total_tokens=u.get("total_tokens", 0),
        )
        return ChatCompletionResponse(
            id=data.get("id", ""),
            object=data.get("object", "chat.completion"),
            created=data.get("created", 0),
            model=data.get("model", ""),
            choices=choices,
            usage=usage,
        )

    @staticmethod
    def _parse_stream_chunk(data: dict) -> StreamChunk:
        choices: list[StreamChoice] = []
        for c in data.get("choices", []):
            delta = c.get("delta", {}) or {}
            choices.append(
                StreamChoice(
                    index=c.get("index", 0),
                    delta=Message(
                        role=delta.get("role", "") or "",
                        content=delta.get("content", "") or "",
                    ),
                    finish_reason=c.get("finish_reason"),
                )
            )
        return StreamChunk(
            id=data.get("id", ""),
            object="chat.completion.chunk",
            created=data.get("created", 0),
            model=data.get("model", ""),
            choices=choices,
        )
