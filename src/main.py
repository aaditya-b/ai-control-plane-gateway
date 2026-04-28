"""FastAPI entry point – wires all subsystems and exposes HTTP endpoints."""

from __future__ import annotations

import logging
import os
import sys
import time

from fastapi import FastAPI, Request

from .abtesting import ABTestManager
from .budget import BudgetManager
from .cache import SemanticCache
from .compression import PromptCompressor
from .config import load_config
from .governance.audit import AuditLogger
from .governance.guardrails import GuardrailEngine
from .governance.pii import PIIRedactor
from .governance.policy import PolicyEngine
from .middleware.auth import auth_middleware
from .middleware.cors import cors_middleware
from .middleware.logging import logging_middleware
from .middleware.rate_limit import rate_limit_middleware
from .observability import MetricsCollector
from .plugin import PluginManager
from .providers.ai21 import AI21Provider
from .providers.anthropic import AnthropicProvider
from .providers.azure import AzureProvider
from .providers.base import BaseProvider
from .providers.bedrock import BedrockProvider
from .providers.cohere import CohereProvider
from .providers.deepseek import DeepSeekProvider
from .providers.fireworks import FireworksProvider
from .providers.google import GoogleProvider
from .providers.groq import GroqProvider
from .providers.huggingface import HuggingFaceProvider
from .providers.mistral import MistralProvider
from .providers.ollama import OllamaProvider
from .providers.openai import OpenAIProvider
from .providers.perplexity import PerplexityProvider
from .providers.replicate import ReplicateProvider
from .providers.together import TogetherProvider
from .providers.xai import XAIProvider
from .proxy import Proxy
from .router import Router

logger = logging.getLogger("gateway")

VERSION = "0.1.0"
_start_time = time.time()

# Mapping from config provider-name (and aliases) to adapter class.
PROVIDER_MAP: dict[str, type[BaseProvider]] = {
    "openai": OpenAIProvider,
    "anthropic": AnthropicProvider,
    "google": GoogleProvider,
    "gemini": GoogleProvider,
    "azure": AzureProvider,
    "bedrock": BedrockProvider,
    "mistral": MistralProvider,
    "groq": GroqProvider,
    "together": TogetherProvider,
    "togetherai": TogetherProvider,
    "deepseek": DeepSeekProvider,
    "xai": XAIProvider,
    "grok": XAIProvider,
    "perplexity": PerplexityProvider,
    "pplx": PerplexityProvider,
    "fireworks": FireworksProvider,
    "ollama": OllamaProvider,
    "cohere": CohereProvider,
    "ai21": AI21Provider,
    "huggingface": HuggingFaceProvider,
    "hf": HuggingFaceProvider,
    "replicate": ReplicateProvider,
}


def create_app(config_path: str | None = None) -> FastAPI:
    """Build and return the fully-configured FastAPI application."""
    cfg = load_config(config_path or os.getenv("GATEWAY_CONFIG"))

    # ── Logging setup ────────────────────────────────────────────────
    level = getattr(logging, cfg.observability.log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s  %(message)s",
        stream=sys.stderr,
    )

    app = FastAPI(title="AI Control Plane Gateway", version=VERSION, docs_url="/docs")

    # ── Providers ────────────────────────────────────────────────────
    providers: dict[str, BaseProvider] = {}
    for pc in cfg.providers:
        cls = PROVIDER_MAP.get(pc.name)
        if cls is None:
            logger.warning("unknown provider '%s', skipping", pc.name)
            continue
        providers[pc.name] = cls(pc)
        logger.info("provider initialized: %s (%d models)", pc.name, len(pc.models))

    if not providers:
        logger.warning("no providers configured; set API keys via config or environment")

    # ── Subsystems ───────────────────────────────────────────────────
    dr_cfg = cfg.governance.data_residency if cfg.governance.data_residency.enabled else None
    rt = Router(providers, cfg.routes, data_residency=dr_cfg)

    sc: SemanticCache | None = None
    if cfg.cache.enabled:
        sc = SemanticCache(
            enabled=True,
            ttl=cfg.cache.ttl,
            max_entries=cfg.cache.max_entries,
        )
        logger.info("semantic cache enabled (ttl=%.0fs, max=%d)", cfg.cache.ttl, cfg.cache.max_entries)

    comp: PromptCompressor | None = None
    if cfg.compression.enabled:
        comp = PromptCompressor(
            max_history_messages=cfg.compression.max_history_messages,
            remove_duplicates=cfg.compression.remove_duplicates,
            trim_whitespace=cfg.compression.trim_whitespace,
        )
        logger.info("prompt compression enabled")

    gr: GuardrailEngine | None = None
    if cfg.governance.guardrails_enabled:
        gr = GuardrailEngine(
            blocked_patterns=cfg.governance.blocked_patterns,
            blocked_topics=cfg.governance.blocked_topics,
            healthcare_mode=cfg.governance.healthcare_mode,
        )
        logger.info("guardrails enabled (healthcare_mode=%s)", cfg.governance.healthcare_mode)

    pii_r: PIIRedactor | None = None
    if cfg.governance.pii_redaction_enabled:
        extra: list[tuple[str, str, str]] = [
            (p[0], p[1], p[2])
            for p in cfg.governance.pii_custom_patterns
            if len(p) >= 3
        ]
        pii_r = PIIRedactor(
            healthcare_phi=cfg.governance.pii_healthcare_entities,
            extra_patterns=extra or None,
        )
        logger.info(
            "PII redaction enabled (healthcare_phi=%s, custom_patterns=%d)",
            cfg.governance.pii_healthcare_entities,
            len(extra),
        )

    audit_l: AuditLogger | None = None
    if cfg.governance.audit_enabled:
        audit_l = AuditLogger(storage_dir=cfg.governance.audit_storage_path)
        logger.info("audit logging enabled at %s", cfg.governance.audit_storage_path)

    policy_e: PolicyEngine | None = None
    if cfg.governance.policy_enabled and cfg.governance.policies:
        policy_e = PolicyEngine(cfg.governance.policies)
        logger.info("policy engine enabled (%d policies)", len(cfg.governance.policies))

    budget_m: BudgetManager | None = None
    if cfg.budget.enabled:
        budget_m = BudgetManager(cfg.budget)
        logger.info("budget management enabled (daily=%.0f)", cfg.budget.default_daily_limit)

    ab: ABTestManager | None = None
    if cfg.ab_testing.enabled and cfg.ab_testing.experiments:
        ab = ABTestManager(cfg.ab_testing.experiments)
        logger.info("A/B testing enabled (%d experiments)", len(cfg.ab_testing.experiments))

    metrics: MetricsCollector | None = None
    if cfg.observability.metrics_enabled:
        metrics = MetricsCollector()
        logger.info("prometheus metrics enabled at /metrics")

    plugin_mgr = PluginManager()

    # ── Proxy ────────────────────────────────────────────────────────
    proxy = Proxy(
        cfg=cfg,
        router=rt,
        cache=sc,
        compressor=comp,
        guardrails=gr,
        pii_redactor=pii_r,
        audit_logger=audit_l,
        policy_engine=policy_e,
        budget_mgr=budget_m,
        ab_tester=ab,
        metrics=metrics,
        plugin_mgr=plugin_mgr,
        providers=providers,
    )

    # ── Middleware (outermost first) ──────────────────────────────────
    app.add_middleware(auth_middleware(valid_keys=cfg.server.api_keys))
    app.add_middleware(rate_limit_middleware())
    app.add_middleware(logging_middleware)
    app.add_middleware(cors_middleware)

    # ── Routes ───────────────────────────────────────────────────────

    @app.post("/v1/chat/completions")
    @app.post("/chat/completions")
    async def chat_completions(request: Request):
        if metrics:
            metrics.increment_active()
        try:
            return await proxy.handle_chat_completion(request)
        finally:
            if metrics:
                metrics.decrement_active()

    @app.get("/health")
    async def health():
        return {
            "status": "ok",
            "version": VERSION,
            "providers": len(providers),
            "uptime": f"{time.time() - _start_time:.0f}s",
            "environment": os.getenv("GATEWAY_ENV", "default"),
        }

    @app.get("/v1/stats")
    async def stats():
        result: dict = {"providers": rt.get_provider_stats()}
        if sc:
            result["cache"] = sc.stats()
        return result

    @app.get("/v1/models")
    async def list_models():
        models = []
        for prov in providers.values():
            for m in prov.models():
                models.append({"id": m, "object": "model", "owned_by": prov.name()})
        return {"object": "list", "data": models}

    if metrics:
        from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

        @app.get("/metrics")
        async def prometheus_metrics():
            from fastapi.responses import Response
            return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

    # ── Startup / Shutdown ────────────────────────────────────────────

    @app.on_event("startup")
    async def startup():
        logger.info("AI Control Plane Gateway v%s started", VERSION)

    @app.on_event("shutdown")
    async def shutdown():
        for prov in providers.values():
            await prov.close()
        if audit_l:
            audit_l.close()

    return app


def main() -> None:
    """CLI entry point."""
    import uvicorn

    config_path = None
    if len(sys.argv) > 1:
        config_path = sys.argv[1]

    app = create_app(config_path)
    cfg = load_config(config_path or os.getenv("GATEWAY_CONFIG"))

    uvicorn.run(
        app,
        host=cfg.server.host,
        port=cfg.server.port,
        workers=cfg.server.workers,
        log_level=cfg.observability.log_level,
    )


if __name__ == "__main__":
    main()
