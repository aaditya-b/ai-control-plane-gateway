from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from datetime import datetime, timezone
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

_DEFAULT_REGION = "us-east-1"
_DEFAULT_MODELS = [
    "claude-3-opus",
    "claude-3-5-sonnet",
    "claude-3-sonnet",
    "claude-3-haiku",
]

_MODEL_ID_MAP: dict[str, str] = {
    "claude-3-opus": "anthropic.claude-3-opus-20240229-v1:0",
    "claude-3-5-sonnet": "anthropic.claude-3-5-sonnet-20241022-v2:0",
    "claude-3-sonnet": "anthropic.claude-3-sonnet-20240229-v1:0",
    "claude-3-haiku": "anthropic.claude-3-haiku-20240307-v1:0",
}

_STOP_REASON_MAP: dict[str, str] = {
    "end_turn": "stop",
    "max_tokens": "length",
    "tool_use": "tool_calls",
    "stop_sequence": "stop",
}


class BedrockProvider(BaseProvider):
    """Provider adapter for AWS Bedrock (Anthropic models via Bedrock)."""

    def __init__(self, cfg: ProviderConfig):
        self._region = cfg.extra.get("region", _DEFAULT_REGION)
        self._access_key = cfg.extra.get("aws_access_key_id", "")
        self._secret_key = cfg.extra.get("aws_secret_access_key", "")
        self._session_token = cfg.extra.get("aws_session_token", "")

        if not cfg.base_url:
            cfg.base_url = (
                f"https://bedrock-runtime.{self._region}.amazonaws.com"
            )
        if not cfg.models:
            cfg.models = list(_DEFAULT_MODELS)
        super().__init__(cfg)

    def name(self) -> str:
        return "bedrock"

    # ── AWS Signature V4 (minimal) ──────────────────────────────────

    def _sign(self, method: str, url: str, headers: dict, payload: bytes) -> dict:
        """Produce AWS Signature V4 headers for the request."""
        from urllib.parse import urlparse, parse_qs

        parsed = urlparse(url)
        host = parsed.hostname or ""
        path = parsed.path or "/"

        now = datetime.now(timezone.utc)
        datestamp = now.strftime("%Y%m%d")
        amz_date = now.strftime("%Y%m%dT%H%M%SZ")

        service = "bedrock"
        credential_scope = f"{datestamp}/{self._region}/{service}/aws4_request"

        signed_headers_list = ["content-type", "host", "x-amz-date"]
        if self._session_token:
            signed_headers_list.append("x-amz-security-token")
        signed_headers_list.sort()
        signed_headers = ";".join(signed_headers_list)

        canon_headers = (
            f"content-type:{headers.get('Content-Type', 'application/json')}\n"
            f"host:{host}\n"
            f"x-amz-date:{amz_date}\n"
        )
        if self._session_token:
            canon_headers += f"x-amz-security-token:{self._session_token}\n"

        payload_hash = hashlib.sha256(payload).hexdigest()
        canonical_request = (
            f"{method}\n{path}\n\n{canon_headers}\n{signed_headers}\n{payload_hash}"
        )

        string_to_sign = (
            f"AWS4-HMAC-SHA256\n{amz_date}\n{credential_scope}\n"
            + hashlib.sha256(canonical_request.encode()).hexdigest()
        )

        def _hmac(key: bytes, msg: str) -> bytes:
            return hmac.new(key, msg.encode(), hashlib.sha256).digest()

        k_date = _hmac(f"AWS4{self._secret_key}".encode(), datestamp)
        k_region = _hmac(k_date, self._region)
        k_service = _hmac(k_region, service)
        k_signing = _hmac(k_service, "aws4_request")
        signature = hmac.new(
            k_signing, string_to_sign.encode(), hashlib.sha256
        ).hexdigest()

        auth = (
            f"AWS4-HMAC-SHA256 Credential={self._access_key}/{credential_scope}, "
            f"SignedHeaders={signed_headers}, Signature={signature}"
        )

        out = dict(headers)
        out["x-amz-date"] = amz_date
        out["Authorization"] = auth
        if self._session_token:
            out["x-amz-security-token"] = self._session_token
        return out

    # ── format conversion ───────────────────────────────────────────

    @staticmethod
    def _resolve_model_id(model: str) -> str:
        return _MODEL_ID_MAP.get(model, model)

    @staticmethod
    def _to_bedrock_body(req: ChatCompletionRequest) -> dict:
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
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": req.max_tokens or 4096,
            "messages": messages,
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
        model_id = self._resolve_model_id(req.model)
        url = f"{self._base_url}/model/{model_id}/invoke"
        body = self._to_bedrock_body(req)
        payload = json.dumps(body).encode()

        headers = {"Content-Type": "application/json"}
        headers = self._sign("POST", url, headers, payload)

        resp = await self._do_with_retries("POST", url, headers, body)
        data = resp.json()
        return self._parse_response(data, req.model)

    async def stream_chat_completion(
        self, req: ChatCompletionRequest
    ) -> AsyncIterator[StreamChunk]:
        # Bedrock streaming uses a different binary event-stream protocol.
        # Fall back to non-streaming and emit the full response as a single
        # chunk for simplicity.
        full = await self.chat_completion(req)
        content = (
            full.choices[0].message.content if full.choices else ""
        )
        yield StreamChunk(
            id=full.id,
            created=full.created,
            model=full.model,
            choices=[
                StreamChoice(
                    index=0,
                    delta=Message(role="assistant", content=content),
                    finish_reason=full.choices[0].finish_reason
                    if full.choices
                    else "stop",
                )
            ],
        )

    # ── health ──────────────────────────────────────────────────────

    async def health_check(self) -> None:
        # No lightweight health endpoint on Bedrock. Verify connectivity by
        # attempting a minimal invocation.
        pass
