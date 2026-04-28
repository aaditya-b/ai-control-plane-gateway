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

_DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com"
_DEFAULT_MODELS = [
    "gemini-1.5-pro",
    "gemini-1.5-flash",
    "gemini-1.0-pro",
]

_FINISH_REASON_MAP: dict[str, str] = {
    "STOP": "stop",
    "MAX_TOKENS": "length",
    "SAFETY": "content_filter",
    "RECITATION": "content_filter",
    "OTHER": "stop",
}


class GoogleProvider(BaseProvider):
    """Provider adapter for the Google Gemini (generativelanguage) API."""

    def __init__(self, cfg: ProviderConfig):
        if not cfg.base_url:
            cfg.base_url = _DEFAULT_BASE_URL
        if not cfg.models:
            cfg.models = list(_DEFAULT_MODELS)
        super().__init__(cfg)

    def name(self) -> str:
        return "google"

    # ── format conversion ───────────────────────────────────────────

    @staticmethod
    def _role(openai_role: str) -> str:
        if openai_role in ("assistant",):
            return "model"
        if openai_role in ("tool", "function"):
            return "user"
        return openai_role  # "user" stays "user"

    @classmethod
    def _to_gemini_body(cls, req: ChatCompletionRequest) -> dict:
        contents: list[dict] = []
        system_parts: list[str] = []

        for m in req.messages:
            if m.role == "system":
                system_parts.append(m.content)
                continue
            contents.append(
                {
                    "role": cls._role(m.role),
                    "parts": [{"text": m.content}],
                }
            )

        body: dict = {"contents": contents}

        if system_parts:
            body["systemInstruction"] = {
                "parts": [{"text": "\n\n".join(system_parts)}]
            }

        gen_config: dict = {}
        if req.temperature is not None:
            gen_config["temperature"] = req.temperature
        if req.top_p is not None:
            gen_config["topP"] = req.top_p
        if req.max_tokens is not None:
            gen_config["maxOutputTokens"] = req.max_tokens
        if req.stop:
            gen_config["stopSequences"] = req.stop
        if gen_config:
            body["generationConfig"] = gen_config

        return body

    @staticmethod
    def _parse_response(data: dict, model: str) -> ChatCompletionResponse:
        choices: list[Choice] = []
        for i, cand in enumerate(data.get("candidates", [])):
            parts = cand.get("content", {}).get("parts", [])
            text = "".join(p.get("text", "") for p in parts)
            finish = _FINISH_REASON_MAP.get(
                cand.get("finishReason", "STOP"), "stop"
            )
            choices.append(
                Choice(
                    index=i,
                    message=Message(role="assistant", content=text),
                    finish_reason=finish,
                )
            )

        u = data.get("usageMetadata", {})
        usage = Usage(
            prompt_tokens=u.get("promptTokenCount", 0),
            completion_tokens=u.get("candidatesTokenCount", 0),
            total_tokens=u.get("totalTokenCount", 0),
        )

        return ChatCompletionResponse(
            id=f"chatcmpl-{uuid.uuid4().hex[:12]}",
            object="chat.completion",
            created=int(time.time()),
            model=model,
            choices=choices,
            usage=usage,
        )

    # ── chat completion ─────────────────────────────────────────────

    async def chat_completion(
        self, req: ChatCompletionRequest
    ) -> ChatCompletionResponse:
        url = (
            f"{self._base_url}/v1/models/{req.model}"
            f":generateContent?key={self._api_key}"
        )
        body = self._to_gemini_body(req)
        headers = {"Content-Type": "application/json"}

        resp = await self._do_with_retries("POST", url, headers, body)
        data = resp.json()
        return self._parse_response(data, req.model)

    async def stream_chat_completion(
        self, req: ChatCompletionRequest
    ) -> AsyncIterator[StreamChunk]:
        url = (
            f"{self._base_url}/v1/models/{req.model}"
            f":streamGenerateContent?alt=sse&key={self._api_key}"
        )
        body = self._to_gemini_body(req)
        headers = {"Content-Type": "application/json"}

        chunk_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
        created = int(time.time())

        async for raw in self._stream_sse("POST", url, headers, body):
            if raw.strip() == "[DONE]":
                return
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue

            for i, cand in enumerate(data.get("candidates", [])):
                parts = cand.get("content", {}).get("parts", [])
                text = "".join(p.get("text", "") for p in parts)
                finish_reason = _FINISH_REASON_MAP.get(
                    cand.get("finishReason", ""), None
                )
                yield StreamChunk(
                    id=chunk_id,
                    created=created,
                    model=req.model,
                    choices=[
                        StreamChoice(
                            index=i,
                            delta=Message(role="assistant", content=text),
                            finish_reason=finish_reason,
                        )
                    ],
                )

    # ── health ──────────────────────────────────────────────────────

    async def health_check(self) -> None:
        url = (
            f"{self._base_url}/v1/models?key={self._api_key}"
        )
        await self._do_with_retries("GET", url, {})
