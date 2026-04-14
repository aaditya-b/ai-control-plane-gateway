"""Prometheus metrics collection."""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

from .types import RequestContext


class MetricsCollector:
    """Exposes nine Prometheus metrics for the gateway."""

    def __init__(self) -> None:
        self.requests_total = Counter(
            "gateway_requests_total",
            "Total gateway requests",
            ["provider", "model", "status"],
        )
        self.request_duration_seconds = Histogram(
            "gateway_request_duration_seconds",
            "Request latency in seconds",
        )
        self.tokens_total = Counter(
            "gateway_tokens_total",
            "Total tokens processed",
            ["provider", "model", "direction"],
        )
        self.cost_dollars_total = Counter(
            "gateway_cost_dollars_total",
            "Cumulative cost in dollars",
        )
        self.cache_hits_total = Counter(
            "gateway_cache_hits_total",
            "Total cache hits",
        )
        self.cache_misses_total = Counter(
            "gateway_cache_misses_total",
            "Total cache misses",
        )
        self.guardrail_violations_total = Counter(
            "gateway_guardrail_violations_total",
            "Total guardrail violations",
        )
        self.pii_detections_total = Counter(
            "gateway_pii_detections_total",
            "Total PII detections",
        )
        self.active_requests = Gauge(
            "gateway_active_requests",
            "Currently in-flight requests",
        )

    # ── Recording helpers ───────────────────────────────────────────

    def record_request(self, ctx: RequestContext) -> None:
        """Record a completed request from its context."""
        status = "ok" if ctx.cost >= 0 else "error"
        self.requests_total.labels(
            provider=ctx.provider,
            model=ctx.model,
            status=status,
        ).inc()

        self.request_duration_seconds.observe(ctx.latency)

        self.tokens_total.labels(
            provider=ctx.provider,
            model=ctx.model,
            direction="input",
        ).inc(ctx.tokens_in)

        self.tokens_total.labels(
            provider=ctx.provider,
            model=ctx.model,
            direction="output",
        ).inc(ctx.tokens_out)

        self.cost_dollars_total.inc(ctx.cost)

    def record_cache_hit(self) -> None:
        self.cache_hits_total.inc()

    def record_cache_miss(self) -> None:
        self.cache_misses_total.inc()

    def record_guardrail_violation(self) -> None:
        self.guardrail_violations_total.inc()

    def record_pii_detection(self) -> None:
        self.pii_detections_total.inc()

    def increment_active(self) -> None:
        self.active_requests.inc()

    def decrement_active(self) -> None:
        self.active_requests.dec()
