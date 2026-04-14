from __future__ import annotations

import json
from typing import AsyncIterator

from ..types import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    Choice,
    GatewayError,
    Message,
    ProviderConfig,
    StreamChunk,
    StreamChoice,
    Usage,
)
from .base import BaseProvider

_DEFAULT_BASE_URL = "https://api.mistral.ai/v1"
_DEFAULT_MODELS = [
    "mistral-large-latest",
    "mistral-medium-latest",
    "mistral-small-latest",
    "open-mixtral-8x22b",
]


class MistralProvider(BaseProvider):
    """Provider adapter for Mistral AI (OpenAI-compatible API)."""

    def __init__(self, cfg: ProviderConfig):
        if not cfg.base_url:
            cfg.base_url = _DEFAULT_BASE_URL
        if not cfg.models:
            cfg.models = list(_DEFAULT_MODELS)
        super().__init__(cfg)

    def name(self) -> str:
        return "mistral"

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    # ── chat completion ─────────────────────────────────────────────

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

    # ── health ──────────────────────────────────────────────────────

    async def health_check(self) -> None:
        url = f"{self._base_url}/models"
        await self._do_with_retries("GET", url, self._headers())

    # ── parsing helpers (OpenAI-compatible format) ──────────────────

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
                        content=msg.get("content", ""),
                    ),
                    finish_reason=c.get("finish_reason", "stop"),
                )
            )

        u = data.get("usage", {})
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
            delta = c.get("delta", {})
            choices.append(
                StreamChoice(
                    index=c.get("index", 0),
                    delta=Message(
                        role=delta.get("role", ""),
                        content=delta.get("content", ""),
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
