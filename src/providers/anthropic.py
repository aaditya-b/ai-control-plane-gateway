from __future__ import annotations

import json
import time
import uuid
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

_DEFAULT_BASE_URL = "https://api.anthropic.com"
_DEFAULT_MODELS = [
    "claude-3-opus",
    "claude-3-5-sonnet",
    "claude-3-sonnet",
    "claude-3-haiku",
]
_ANTHROPIC_VERSION = "2023-06-01"

_STOP_REASON_MAP: dict[str, str] = {
    "end_turn": "stop",
    "max_tokens": "length",
    "tool_use": "tool_calls",
    "stop_sequence": "stop",
}


class AnthropicProvider(BaseProvider):
    """Provider adapter for the Anthropic Messages API."""

    def __init__(self, cfg: ProviderConfig):
        if not cfg.base_url:
            cfg.base_url = _DEFAULT_BASE_URL
        if not cfg.models:
            cfg.models = list(_DEFAULT_MODELS)
        super().__init__(cfg)

    def name(self) -> str:
        return "anthropic"

    def _headers(self) -> dict[str, str]:
        return {
            "x-api-key": self._api_key,
            "anthropic-version": _ANTHROPIC_VERSION,
            "Content-Type": "application/json",
        }

    # ── format conversion ───────────────────────────────────────────

    @staticmethod
    def _to_anthropic_body(req: ChatCompletionRequest) -> dict:
        system_parts: list[str] = []
        messages: list[dict] = []

        for m in req.messages:
            if m.role == "system":
                system_parts.append(m.content)
                continue
            role = m.role
            if role in ("tool", "function"):
                role = "user"
            messages.append({"role": role, "content": m.content})

        body: dict = {
            "model": req.model,
            "messages": messages,
            "max_tokens": req.max_tokens or 4096,
        }

        if system_parts:
            body["system"] = "\n\n".join(system_parts)
        if req.temperature is not None:
            body["temperature"] = req.temperature
        if req.top_p is not None:
            body["top_p"] = req.top_p
        if req.stop:
            body["stop_sequences"] = req.stop

        return body

    @staticmethod
    def _parse_response(data: dict, model: str) -> ChatCompletionResponse:
        # Combine all text content blocks into a single string.
        content_parts: list[str] = []
        for block in data.get("content", []):
            if block.get("type") == "text":
                content_parts.append(block.get("text", ""))

        stop_reason = _STOP_REASON_MAP.get(
            data.get("stop_reason", "end_turn"), "stop"
        )

        u = data.get("usage", {})
        usage = Usage(
            prompt_tokens=u.get("input_tokens", 0),
            completion_tokens=u.get("output_tokens", 0),
            total_tokens=u.get("input_tokens", 0) + u.get("output_tokens", 0),
        )

        return ChatCompletionResponse(
            id=data.get("id", f"chatcmpl-{uuid.uuid4().hex[:12]}"),
            object="chat.completion",
            created=int(time.time()),
            model=model,
            choices=[
                Choice(
                    index=0,
                    message=Message(
                        role="assistant",
                        content="".join(content_parts),
                    ),
                    finish_reason=stop_reason,
                )
            ],
            usage=usage,
        )

    # ── chat completion ─────────────────────────────────────────────

    async def chat_completion(
        self, req: ChatCompletionRequest
    ) -> ChatCompletionResponse:
        url = f"{self._base_url}/v1/messages"
        body = self._to_anthropic_body(req)

        resp = await self._do_with_retries("POST", url, self._headers(), body)
        data = resp.json()
        return self._parse_response(data, req.model)

    async def stream_chat_completion(
        self, req: ChatCompletionRequest
    ) -> AsyncIterator[StreamChunk]:
        url = f"{self._base_url}/v1/messages"
        body = self._to_anthropic_body(req)
        body["stream"] = True

        chunk_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
        created = int(time.time())
        model = req.model

        async for raw in self._stream_sse("POST", url, self._headers(), body):
            if raw.strip() == "[DONE]":
                return
            try:
                event = json.loads(raw)
            except json.JSONDecodeError:
                continue

            event_type = event.get("type", "")

            if event_type == "message_start":
                msg = event.get("message", {})
                model = msg.get("model", model)
                chunk_id = msg.get("id", chunk_id)
                # Emit an initial role chunk.
                yield StreamChunk(
                    id=chunk_id,
                    created=created,
                    model=model,
                    choices=[
                        StreamChoice(
                            index=0,
                            delta=Message(role="assistant", content=""),
                        )
                    ],
                )

            elif event_type == "content_block_delta":
                delta = event.get("delta", {})
                text = delta.get("text", "")
                if text:
                    yield StreamChunk(
                        id=chunk_id,
                        created=created,
                        model=model,
                        choices=[
                            StreamChoice(
                                index=0,
                                delta=Message(role="", content=text),
                            )
                        ],
                    )

            elif event_type == "message_delta":
                stop_reason = _STOP_REASON_MAP.get(
                    event.get("delta", {}).get("stop_reason", "end_turn"),
                    "stop",
                )
                yield StreamChunk(
                    id=chunk_id,
                    created=created,
                    model=model,
                    choices=[
                        StreamChoice(
                            index=0,
                            delta=Message(role="", content=""),
                            finish_reason=stop_reason,
                        )
                    ],
                )

            elif event_type == "message_stop":
                return

    # ── health ──────────────────────────────────────────────────────

    async def health_check(self) -> None:
        # Anthropic has no lightweight /models endpoint; send a minimal
        # messages request with max_tokens=1 to verify connectivity.
        url = f"{self._base_url}/v1/messages"
        body = {
            "model": self._models[0] if self._models else "claude-3-haiku",
            "max_tokens": 1,
            "messages": [{"role": "user", "content": "hi"}],
        }
        await self._do_with_retries("POST", url, self._headers(), body)
