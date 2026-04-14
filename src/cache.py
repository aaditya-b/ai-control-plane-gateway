"""Semantic LRU cache with TTL support."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections import OrderedDict
from dataclasses import dataclass, field

from .types import ChatCompletionRequest, ChatCompletionResponse


@dataclass
class CacheEntry:
    response: ChatCompletionResponse
    created_at: float = field(default_factory=time.time)
    expires_at: float = 0.0
    hit_count: int = 0


@dataclass
class CacheStats:
    hits: int = 0
    misses: int = 0

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return self.hits / total if total > 0 else 0.0


class SemanticCache:
    """Thread-safe LRU cache with TTL expiration."""

    def __init__(self, max_entries: int = 10_000, ttl: float = 300.0) -> None:
        self._max_entries = max_entries
        self._ttl = ttl
        self._cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self._lock = asyncio.Lock()
        self._stats = CacheStats()

    # ── Key generation ──────────────────────────────────────────────

    @staticmethod
    def cache_key(request: ChatCompletionRequest) -> str:
        """SHA256 of model + temperature + normalised messages."""
        normalized_messages = [
            {"role": m.role, "content": m.content}
            for m in request.messages
        ]
        payload = json.dumps(
            {
                "model": request.model,
                "temperature": request.temperature,
                "messages": normalized_messages,
            },
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode()).hexdigest()

    # ── Public API ──────────────────────────────────────────────────

    async def get(self, request: ChatCompletionRequest) -> ChatCompletionResponse | None:
        key = self.cache_key(request)
        async with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                self._stats.misses += 1
                return None

            # TTL check
            if time.time() > entry.expires_at:
                del self._cache[key]
                self._stats.misses += 1
                return None

            # LRU: move to end (most-recently used)
            self._cache.move_to_end(key)
            entry.hit_count += 1
            self._stats.hits += 1
            return entry.response

    async def set(self, request: ChatCompletionRequest, response: ChatCompletionResponse) -> None:
        key = self.cache_key(request)
        now = time.time()
        async with self._lock:
            # Update existing or insert new
            if key in self._cache:
                self._cache.move_to_end(key)
            self._cache[key] = CacheEntry(
                response=response,
                created_at=now,
                expires_at=now + self._ttl,
            )
            # Evict LRU entries if over capacity
            while len(self._cache) > self._max_entries:
                self._cache.popitem(last=False)

    async def clear(self) -> None:
        async with self._lock:
            self._cache.clear()

    @property
    def stats(self) -> CacheStats:
        return self._stats

    @property
    def size(self) -> int:
        return len(self._cache)
