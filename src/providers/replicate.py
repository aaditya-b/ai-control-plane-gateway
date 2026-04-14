"""Replicate – model-hosting platform.

Replicate uses a prediction-based async API. For chat models (e.g. Llama,
Mixtral via Replicate), we call the synchronous ``/v1/models/{owner}/{name}/predictions``
endpoint with ``Prefer: wait`` to block until the prediction completes.

Not all Replicate models are chat models; we expose the common chat-tuned
ones by default. The caller supplies ``model`` as ``owner/name`` (e.g.
``meta/meta-llama-3.1-70b-instruct``).
"""

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
    StreamChoice,
    StreamChunk,
    Usage,
)
from .base import BaseProvider

_DEFAULT_BASE_URL = "https://api.replicate.com"
_DEFAULT_MODELS = [
    "meta/meta-llama-3.1-405b-instruct",
    "meta/meta-llama-3.1-70b-instruct",
    "meta/meta-llama-3.1-8b-instruct",
    "mistralai/mixtral-8x7b-instruct-v0.1",
    "mistralai/mistral-7b-instruct-v0.2",
]


class ReplicateProvider(BaseProvider):
    """Adapter for Replicate's prediction API."""

    def __init__(self, cfg: ProviderConfig):
        if not cfg.base_url:
            cfg.base_url = _DEFAULT_BASE_URL
        if not cfg.models:
            cfg.models = list(_DEFAULT_MODELS)
        super().__init__(cfg)

    def name(self) -> str:
        return "replicate"

    def _headers(self, *, wait: bool = False) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        if wait:
            headers["Prefer"] = "wait"
        return headers

    @staticmethod
    def _messages_to_prompt(req: ChatCompletionRequest) -> tuple[str, str]:
        """Flatten messages into (prompt, system_prompt) for Replicate chat models."""
        system_parts: list[str] = []
        convo_parts: list[str] = []
        for m in req.messages:
            if m.role == "system":
                system_parts.append(m.content)
            elif m.role == "assistant":
                convo_parts.append(f"Assistant: {m.content}")
            else:
                convo_parts.append(f"User: {m.content}")
        convo_parts.append("Assistant:")
        return "\n".join(convo_parts), "\n\n".join(system_parts)

    def _input_dict(self, req: ChatCompletionRequest) -> dict:
        prompt, system_prompt = self._messages_to_prompt(req)
        payload: dict = {"prompt": prompt}
        if system_prompt:
            payload["system_prompt"] = system_prompt
        if req.temperature is not None:
            payload["temperature"] = req.temperature
        if req.top_p is not None:
            payload["top_p"] = req.top_p
        if req.max_tokens is not None:
            payload["max_tokens"] = req.max_tokens
        return payload

    async def chat_completion(
        self, req: ChatCompletionRequest
    ) -> ChatCompletionResponse:
        url = f"{self._base_url}/v1/models/{req.model}/predictions"
        body = {"input": self._input_dict(req)}
        resp = await self._do_with_retries(
            "POST", url, self._headers(wait=True), body
        )
        data = resp.json()

        if data.get("status") == "failed":
            raise GatewayError(
                502,
                f"replicate prediction failed: {data.get('error')}",
                self.name(),
                False,
            )

        output = data.get("output", "")
        if isinstance(output, list):
            text = "".join(str(x) for x in output)
        else:
            text = str(output) if output is not None else ""

        # Replicate doesn't return token counts for most chat models.
        from ..util import estimate_tokens
        prompt_tokens = estimate_tokens(self._messages_to_prompt(req)[0])
        completion_tokens = estimate_tokens(text)

        return ChatCompletionResponse(
            id=data.get("id", f"chatcmpl-{uuid.uuid4().hex[:12]}"),
            object="chat.completion",
            created=int(time.time()),
            model=req.model,
            choices=[
                Choice(
                    index=0,
                    message=Message(role="assistant", content=text),
                    finish_reason="stop",
                )
            ],
            usage=Usage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
            ),
        )

    async def stream_chat_completion(
        self, req: ChatCompletionRequest
    ) -> AsyncIterator[StreamChunk]:
        # Replicate streaming uses a separate SSE stream URL returned by
        # the initial prediction. For simplicity, fall back to non-streaming
        # and emit the full response as a single chunk.
        resp = await self.chat_completion(req)
        chunk_id = resp.id
        if resp.choices:
            yield StreamChunk(
                id=chunk_id,
                object="chat.completion.chunk",
                created=resp.created,
                model=resp.model,
                choices=[
                    StreamChoice(
                        index=0,
                        delta=Message(
                            role="assistant",
                            content=resp.choices[0].message.content,
                        ),
                        finish_reason="stop",
                    )
                ],
            )

    async def health_check(self) -> None:
        # Replicate's /v1/account is authenticated and lightweight.
        url = f"{self._base_url}/v1/account"
        await self._do_with_retries("GET", url, self._headers())
