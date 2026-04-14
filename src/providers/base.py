from __future__ import annotations

import abc
import asyncio

import httpx

from ..types import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    GatewayError,
    ProviderConfig,
    StreamChunk,
)
from typing import AsyncIterator


class BaseProvider(abc.ABC):
    """Abstract base for all LLM provider adapters."""

    def __init__(self, cfg: ProviderConfig):
        self._api_key = cfg.api_key
        self._base_url = cfg.base_url.rstrip("/")
        self._models = cfg.models
        self._max_retries = cfg.max_retries or 3
        self._timeout = cfg.timeout or 30.0
        self._client = httpx.AsyncClient(timeout=self._timeout)

    # ── identity ────────────────────────────────────────────────────

    @abc.abstractmethod
    def name(self) -> str: ...

    def models(self) -> list[str]:
        return self._models

    # ── chat completion ─────────────────────────────────────────────

    @abc.abstractmethod
    async def chat_completion(
        self, req: ChatCompletionRequest
    ) -> ChatCompletionResponse: ...

    @abc.abstractmethod
    async def stream_chat_completion(
        self, req: ChatCompletionRequest
    ) -> AsyncIterator[StreamChunk]: ...

    # ── health ──────────────────────────────────────────────────────

    @abc.abstractmethod
    async def health_check(self) -> None: ...

    # ── helpers ─────────────────────────────────────────────────────

    async def _do_with_retries(
        self,
        method: str,
        url: str,
        headers: dict,
        json_data: dict | None = None,
    ) -> httpx.Response:
        last_err: Exception | None = None
        for attempt in range(self._max_retries + 1):
            if attempt > 0:
                await asyncio.sleep(0.5 * (2 ** (attempt - 1)))
            try:
                resp = await self._client.request(
                    method, url, headers=headers, json=json_data
                )
                if resp.status_code == 200:
                    return resp
                retryable = resp.status_code == 429 or resp.status_code >= 500
                last_err = GatewayError(
                    resp.status_code,
                    f"API error: {resp.text}",
                    self.name(),
                    retryable,
                )
                if not retryable:
                    raise last_err
            except httpx.HTTPError as e:
                last_err = GatewayError(
                    502, f"request failed: {e}", self.name(), True
                )
        raise last_err  # type: ignore[misc]

    async def _stream_sse(
        self, method: str, url: str, headers: dict, json_data: dict
    ) -> AsyncIterator[str]:
        async with self._client.stream(
            method, url, headers=headers, json=json_data
        ) as resp:
            if resp.status_code != 200:
                body = await resp.aread()
                raise GatewayError(
                    resp.status_code,
                    f"API error: {body.decode()}",
                    self.name(),
                    resp.status_code >= 500,
                )
            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    yield line[6:]

    async def close(self) -> None:
        await self._client.aclose()
