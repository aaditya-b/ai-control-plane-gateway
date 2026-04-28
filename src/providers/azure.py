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

_DEFAULT_API_VERSION = "2024-02-01"
_DEFAULT_MODELS = [
    "gpt-4o",
    "gpt-4o-mini",
    "gpt-4-turbo",
    "gpt-35-turbo",
]


class AzureProvider(BaseProvider):
    """Provider adapter for Azure OpenAI Service."""

    def __init__(self, cfg: ProviderConfig):
        if not cfg.models:
            cfg.models = list(_DEFAULT_MODELS)
        super().__init__(cfg)
        self._api_version = cfg.extra.get("api_version", _DEFAULT_API_VERSION)

    def name(self) -> str:
        return "azure"

    def _headers(self) -> dict[str, str]:
        return {
            "api-key": self._api_key,
            "Content-Type": "application/json",
        }

    def _url(self, model: str) -> str:
        return (
            f"{self._base_url}/openai/deployments/{model}"
            f"/chat/completions?api-version={self._api_version}"
        )

    # ── chat completion ─────────────────────────────────────────────

    async def chat_completion(
        self, req: ChatCompletionRequest
    ) -> ChatCompletionResponse:
        url = self._url(req.model)
        body = req.model_dump(exclude_none=True)
        body["stream"] = False

        resp = await self._do_with_retries("POST", url, self._headers(), body)
        data = resp.json()
        return self._parse_response(data)

    async def stream_chat_completion(
        self, req: ChatCompletionRequest
    ) -> AsyncIterator[StreamChunk]:
        url = self._url(req.model)
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
        # Azure doesn't have a single /models endpoint; verify by listing
        # deployments or simply hitting the completions endpoint header-only.
        model = self._models[0] if self._models else "gpt-4o"
        url = self._url(model)
        # Sending an empty body will return an error, but a 4xx proves
        # connectivity. We use a minimal valid request instead.
        body = {
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 1,
        }
        await self._do_with_retries("POST", url, self._headers(), body)

    # ── parsing helpers (same format as OpenAI) ─────────────────────

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
