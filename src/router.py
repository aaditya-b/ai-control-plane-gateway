"""Intelligent router with six strategies and a circuit breaker."""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from threading import Lock
from typing import TYPE_CHECKING

from .types import ChatCompletionRequest, GatewayError, RouteConfig, RoutingStrategy

if TYPE_CHECKING:
    from .providers.base import BaseProvider


@dataclass
class ProviderState:
    avg_latency: float = 0.0
    error_rate: float = 0.0
    request_count: int = 0
    error_count: int = 0
    circuit_open: bool = False
    circuit_until: float = 0.0

    # Running totals for latency averaging
    _total_latency: float = 0.0


_CIRCUIT_ERROR_THRESHOLD = 0.50   # >50 % error rate
_CIRCUIT_MIN_REQUESTS = 10        # minimum requests before evaluation
_CIRCUIT_COOLDOWN = 30.0          # seconds


class Router:
    """Select a provider for a given request using the configured strategy."""

    def __init__(
        self,
        providers: dict[str, BaseProvider],
        routes: list[RouteConfig],
    ) -> None:
        self._providers = providers
        self._routes = routes
        self._provider_states: dict[str, ProviderState] = {}
        self._rr_counter = 0
        self._lock = Lock()

    # ── Public API ──────────────────────────────────────────────────

    async def route(self, req: ChatCompletionRequest) -> BaseProvider:
        """Return the selected provider instance for the given request."""
        route_cfg = self._find_route(req.model)
        if route_cfg is None:
            raise GatewayError(404, f"no route configured for model {req.model}")

        # Determine candidate providers:
        #  - if route lists providers explicitly, use those
        #  - otherwise auto-discover any configured provider that advertises the model
        if route_cfg.providers:
            candidates = [p for p in route_cfg.providers if p in self._providers]
        else:
            candidates = [
                name for name, prov in self._providers.items()
                if req.model in prov.models()
            ]

        if not candidates:
            raise GatewayError(
                404,
                f"no provider configured for model {req.model}",
            )

        available = self._available_providers(candidates)
        if not available:
            raise GatewayError(503, "all providers are circuit-open", retryable=True)

        strategy = RoutingStrategy(route_cfg.strategy)
        selected_name = self._select(strategy, available, route_cfg)
        return self._providers[selected_name]

    def record_latency(self, provider: str, latency: float) -> None:
        with self._lock:
            state = self._ensure_state(provider)
            state.request_count += 1
            state._total_latency += latency
            state.avg_latency = state._total_latency / state.request_count
            self._evaluate_circuit(state)

    def record_error(self, provider: str) -> None:
        with self._lock:
            state = self._ensure_state(provider)
            state.request_count += 1
            state.error_count += 1
            state.error_rate = state.error_count / state.request_count
            self._evaluate_circuit(state)

    @property
    def provider_states(self) -> dict[str, ProviderState]:
        return dict(self._provider_states)

    def get_provider_stats(self) -> dict[str, dict[str, float | int | bool]]:
        """Return a JSON-serialisable snapshot of per-provider state."""
        snapshot: dict[str, dict[str, float | int | bool]] = {}
        for name in self._providers:
            state = self._provider_states.get(name, ProviderState())
            snapshot[name] = {
                "avg_latency": round(state.avg_latency, 4),
                "error_rate": round(state.error_rate, 4),
                "request_count": state.request_count,
                "error_count": state.error_count,
                "circuit_open": state.circuit_open,
            }
        return snapshot

    # ── Route matching ──────────────────────────────────────────────

    def _find_route(self, model: str) -> RouteConfig | None:
        # First pass: exact match on a route that names the model
        for r in self._routes:
            if model in r.models:
                return r
        # Second pass: wildcard / catch-all route
        for r in self._routes:
            if not r.models or "*" in r.models:
                return r
        return None

    # ── Circuit breaker ─────────────────────────────────────────────

    def _available_providers(self, providers: list[str]) -> list[str]:
        now = time.time()
        available: list[str] = []
        for p in providers:
            state = self._provider_states.get(p)
            if state is None:
                available.append(p)
                continue
            if state.circuit_open:
                # Half-open probe: allow one request after cooldown
                if now >= state.circuit_until:
                    state.circuit_open = False
                    available.append(p)
            else:
                available.append(p)
        return available

    def _evaluate_circuit(self, state: ProviderState) -> None:
        if state.request_count < _CIRCUIT_MIN_REQUESTS:
            return
        state.error_rate = state.error_count / state.request_count
        if state.error_rate > _CIRCUIT_ERROR_THRESHOLD:
            state.circuit_open = True
            state.circuit_until = time.time() + _CIRCUIT_COOLDOWN

    def _ensure_state(self, provider: str) -> ProviderState:
        if provider not in self._provider_states:
            self._provider_states[provider] = ProviderState()
        return self._provider_states[provider]

    # ── Strategy implementations ────────────────────────────────────

    def _select(
        self,
        strategy: RoutingStrategy,
        available: list[str],
        route: RouteConfig,
    ) -> str:
        if strategy == RoutingStrategy.ROUND_ROBIN:
            return self._round_robin(available)
        if strategy == RoutingStrategy.WEIGHTED:
            return self._weighted(available, route)
        if strategy == RoutingStrategy.LEAST_LATENCY:
            return self._least_latency(available)
        if strategy == RoutingStrategy.COST_OPTIMIZED:
            return self._cost_optimized(available, route)
        if strategy == RoutingStrategy.QUALITY:
            return self._quality(available, route)
        if strategy == RoutingStrategy.FALLBACK:
            return self._fallback(available)
        raise GatewayError(400, f"unknown strategy: {strategy}")

    def _round_robin(self, available: list[str]) -> str:
        with self._lock:
            idx = self._rr_counter % len(available)
            self._rr_counter += 1
        return available[idx]

    @staticmethod
    def _weighted(available: list[str], route: RouteConfig) -> str:
        weights = [route.weights.get(p, 1) for p in available]
        total = sum(weights)
        roll = random.uniform(0, total)
        cumulative = 0.0
        for provider, w in zip(available, weights):
            cumulative += w
            if roll <= cumulative:
                return provider
        return available[-1]

    def _least_latency(self, available: list[str]) -> str:
        return min(
            available,
            key=lambda p: self._provider_states.get(p, ProviderState()).avg_latency,
        )

    @staticmethod
    def _cost_optimized(available: list[str], route: RouteConfig) -> str:
        return min(
            available,
            key=lambda p: route.cost_per_token.get(p, float("inf")),
        )

    @staticmethod
    def _quality(available: list[str], route: RouteConfig) -> str:
        return max(
            available,
            key=lambda p: route.quality_scores.get(p, 0.0),
        )

    @staticmethod
    def _fallback(available: list[str]) -> str:
        return available[0]
