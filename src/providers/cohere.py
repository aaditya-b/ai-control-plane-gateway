"""Cohere – Command R / R+ family. Uses Cohere's /v2/chat endpoint."""

from __future__ import annotations

import json
import time
import uuid
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

_DEFAULT_BASE_URL = "https://api.cohere.com"
_DEFAULT_MODELS = [
    "command-r-plus",
    "command-r",
    "command-r-08-2024",
    "command-r-plus-08-2024",
]

# Cohere finish-reason → OpenAI finish-reason
_FINISH_REASON_MAP = {
    "COMPLETE": "stop",
    "MAX_TOKENS": "length",
    "STOP_SEQUENCE": "stop",
    "ERROR": "stop",
    "ERROR_TOXIC": "content_filter",
    "USER_CANCEL": "stop",
}


class CohereProvider(BaseProvider):
    """Adapter for Cohere's chat API (v2)."""

    def __init__(self, cfg: ProviderConfig):
        if not cfg.base_url:
            cfg.base_url = _DEFAULT_BASE_URL
        if not cfg.models:
            cfg.models = list(_DEFAULT_MODELS)
        super().__init__(cfg)

    def name(self) -> str:
        return "cohere"

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    # ── format conversion ───────────────────────────────────────────

    @staticmethod
    def _to_cohere_body(req: ChatCompletionRequest) -> dict:
        # Cohere v2/chat accepts OpenAI-style messages directly.
        messages = [
            {"role": m.role, "content": m.content}
            for m in req.messages
        ]
        body: dict = {
            "model": req.model,
            "messages": messages,
        }
        if req.temperature is not None:
            body["temperature"] = req.temperature
        if req.max_tokens is not None:
            body["max_tokens"] = req.max_tokens
        if req.top_p is not None:
            body["p"] = req.top_p
        if req.stop:
            body["stop_sequences"] = req.stop
        return body

    @staticmethod
    def _parse_response(data: dict, model: str) -> ChatCompletionResponse:
        # Cohere v2 response structure:
        #   {id, finish_reason, message:{role,content:[{type:"text",text:...}]},
        #    usage:{tokens:{input_tokens,output_tokens}}}
        msg = data.get("message", {})
        content_blocks = msg.get("content", []) or []
        text = "".join(
            b.get("text", "")
            for b in content_blocks
            if b.get("type", "text") == "text"
        )

        finish = _FINISH_REASON_MAP.get(data.get("finish_reason", "COMPLETE"), "stop")

        usage_root = data.get("usage", {}) or {}
        tokens = usage_root.get("tokens", {}) or usage_root.get("billed_units", {}) or {}
        prompt_tokens = tokens.get("input_tokens", 0)
        completion_tokens = tokens.get("output_tokens", 0)

        return ChatCompletionResponse(
            id=data.get("id", f"chatcmpl-{uuid.uuid4().hex[:12]}"),
            object="chat.completion",
            created=int(time.time()),
            model=model,
            choices=[
                Choice(
                    index=0,
                    message=Message(role="assistant", content=text),
                    finish_reason=finish,
                )
            ],
            usage=Usage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
            ),
        )

    # ── chat completion ─────────────────────────────────────────────

    async def chat_completion(
        self, req: ChatCompletionRequest
    ) -> ChatCompletionResponse:
        url = f"{self._base_url}/v2/chat"
        body = self._to_cohere_body(req)
        resp = await self._do_with_retries("POST", url, self._headers(), body)
        return self._parse_response(resp.json(), req.model)

    async def stream_chat_completion(
        self, req: ChatCompletionRequest
    ) -> AsyncIterator[StreamChunk]:
        url = f"{self._base_url}/v2/chat"
        body = self._to_cohere_body(req)
        body["stream"] = True

        chunk_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
        created = int(time.time())

        async for raw in self._stream_sse("POST", url, self._headers(), body):
            if not raw.strip():
                continue
            try:
                event = json.loads(raw)
            except json.JSONDecodeError:
                continue

            event_type = event.get("type", "")

            if event_type == "content-delta":
                delta = event.get("delta", {}).get("message", {}).get("content", {})
                text = delta.get("text", "")
                if text:
                    yield StreamChunk(
                        id=chunk_id,
                        created=created,
                        model=req.model,
                        choices=[
                            StreamChoice(
                                index=0,
                                delta=Message(role="", content=text),
                            )
                        ],
                    )
            elif event_type == "message-end":
                finish = _FINISH_REASON_MAP.get(
                    event.get("delta", {}).get("finish_reason", "COMPLETE"),
                    "stop",
                )
                yield StreamChunk(
                    id=chunk_id,
                    created=created,
                    model=req.model,
                    choices=[
                        StreamChoice(
                            index=0,
                            delta=Message(role="", content=""),
                            finish_reason=finish,
                        )
                    ],
                )
                return

    async def health_check(self) -> None:
        url = f"{self._base_url}/v1/models"
        await self._do_with_retries("GET", url, self._headers())
