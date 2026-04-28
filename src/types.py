"""Core types for the AI Control Plane Gateway (OpenAI-compatible)."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

# ── OpenAI-compatible request / response models ──────────────────────


class FunctionCall(BaseModel):
    name: str
    arguments: str


class ToolCall(BaseModel):
    id: str
    type: str = "function"
    function: FunctionCall


class Message(BaseModel):
    role: str
    content: str = ""
    name: str | None = None
    tool_calls: list[ToolCall] | None = None


class Tool(BaseModel):
    type: str = "function"
    function: dict[str, Any] | None = None


class ChatCompletionRequest(BaseModel):
    model: str
    messages: list[Message]
    temperature: float | None = None
    max_tokens: int | None = None
    top_p: float | None = None
    stream: bool = False
    stop: list[str] | None = None
    presence_penalty: float | None = None
    frequency_penalty: float | None = None
    user: str | None = None
    tools: list[Tool] | None = None
    tool_choice: Any | None = None


class Choice(BaseModel):
    index: int = 0
    message: Message
    finish_reason: str = "stop"


class Usage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ChatCompletionResponse(BaseModel):
    id: str = Field(default_factory=lambda: f"chatcmpl-{uuid.uuid4().hex[:12]}")
    object: str = "chat.completion"
    created: int = Field(default_factory=lambda: int(time.time()))
    model: str = ""
    choices: list[Choice] = Field(default_factory=list)
    usage: Usage = Field(default_factory=Usage)


class StreamChoice(BaseModel):
    index: int = 0
    delta: Message = Field(default_factory=lambda: Message(role="assistant"))
    finish_reason: str | None = None


class StreamChunk(BaseModel):
    id: str = Field(default_factory=lambda: f"chatcmpl-{uuid.uuid4().hex[:12]}")
    object: str = "chat.completion.chunk"
    created: int = Field(default_factory=lambda: int(time.time()))
    model: str = ""
    choices: list[StreamChoice] = Field(default_factory=list)


# ── Configuration models ─────────────────────────────────────────────


class ProviderConfig(BaseModel):
    name: str
    api_key: str = ""
    base_url: str = ""
    models: list[str] = Field(default_factory=list)
    timeout: float = 30.0
    max_retries: int = 3
    extra: dict[str, str] = Field(default_factory=dict)


class RouteConfig(BaseModel):
    name: str = ""
    strategy: str = "round-robin"
    providers: list[str] = Field(default_factory=list)
    weights: dict[str, int] = Field(default_factory=dict)
    quality_scores: dict[str, float] = Field(default_factory=dict)
    cost_per_token: dict[str, float] = Field(default_factory=dict)
    models: list[str] = Field(default_factory=list)


class PolicyRule(BaseModel):
    field: str
    operator: str  # eq, neq, gt, lt, in, not_in, matches
    value: Any


class PolicyConfig(BaseModel):
    name: str
    description: str = ""
    action: str = "deny"  # allow, deny, warn
    priority: int = 0
    rules: list[PolicyRule] = Field(default_factory=list)


class ExperimentConfig(BaseModel):
    name: str
    models: list[str] = Field(default_factory=list)
    traffic_split: list[float] = Field(default_factory=list)
    enabled: bool = True


# ── Runtime context ──────────────────────────────────────────────────


@dataclass
class RequestContext:
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    user_id: str = ""
    team_id: str = ""
    api_key: str = ""
    model: str = ""
    provider: str = ""
    start_time: float = field(default_factory=time.time)
    latency: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    cost: float = 0.0
    cache_hit: bool = False
    ab_test_group: str = ""
    metadata: dict[str, str] = field(default_factory=dict)


# ── Error types ──────────────────────────────────────────────────────


class GatewayError(Exception):
    def __init__(self, code: int, message: str, provider: str = "", retryable: bool = False):
        self.code = code
        self.message = message
        self.provider = provider
        self.retryable = retryable
        super().__init__(message)


# ── Routing strategy enum ────────────────────────────────────────────


class RoutingStrategy(str, Enum):
    ROUND_ROBIN = "round-robin"
    WEIGHTED = "weighted"
    LEAST_LATENCY = "least-latency"
    COST_OPTIMIZED = "cost-optimized"
    QUALITY = "quality"
    FALLBACK = "fallback"
