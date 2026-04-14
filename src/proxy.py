"""Core proxy pipeline – 13-stage request processing."""

from __future__ import annotations

import json
import logging
import time
from typing import TYPE_CHECKING

from fastapi import Request
from fastapi.responses import JSONResponse, StreamingResponse

from .types import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    GatewayError,
    RequestContext,
)
from .util import calculate_cost, estimate_tokens, generate_request_id

if TYPE_CHECKING:
    from .abtesting import ABTestManager
    from .budget import BudgetManager
    from .cache import SemanticCache
    from .compression import PromptCompressor
    from .config import GatewayConfig
    from .governance.audit import AuditLogger
    from .governance.guardrails import GuardrailEngine
    from .governance.pii import PIIMatch, PIIRedactor
    from .governance.policy import PolicyEngine
    from .observability import MetricsCollector
    from .plugin import PluginManager
    from .providers.base import BaseProvider
    from .router import Router

logger = logging.getLogger("gateway")


class Proxy:
    """Orchestrates the full request pipeline."""

    def __init__(
        self,
        cfg: GatewayConfig,
        router: Router,
        cache: SemanticCache | None,
        compressor: PromptCompressor | None,
        guardrails: GuardrailEngine | None,
        pii_redactor: PIIRedactor | None,
        audit_logger: AuditLogger | None,
        policy_engine: PolicyEngine | None,
        budget_mgr: BudgetManager | None,
        ab_tester: ABTestManager | None,
        metrics: MetricsCollector | None,
        plugin_mgr: PluginManager | None,
        providers: dict[str, BaseProvider],
    ) -> None:
        self.cfg = cfg
        self.router = router
        self.cache = cache
        self.compressor = compressor
        self.guardrails = guardrails
        self.pii_redactor = pii_redactor
        self.audit_logger = audit_logger
        self.policy_engine = policy_engine
        self.budget_mgr = budget_mgr
        self.ab_tester = ab_tester
        self.metrics = metrics
        self.plugin_mgr = plugin_mgr
        self.providers = providers

    async def handle_chat_completion(self, request: Request) -> JSONResponse | StreamingResponse:
        """Full 13-stage pipeline for /v1/chat/completions."""
        req_ctx = RequestContext(
            request_id=generate_request_id(),
            start_time=time.time(),
        )
        req_ctx.user_id = request.headers.get("x-user-id", "")
        req_ctx.team_id = request.headers.get("x-team-id", "")

        # Parse body
        try:
            body = await request.json()
            req = ChatCompletionRequest(**body)
        except Exception as e:
            return _error_response(400, f"invalid request: {e}")

        if not req.model:
            return _error_response(400, "model field is required")

        # --- Stage 1: Policy Evaluation ---
        if self.policy_engine and self.cfg.governance.policy_enabled:
            decision = self.policy_engine.evaluate(req_ctx, req)
            if not decision.allowed:
                self._log_audit(req_ctx, req, None, "policy_denied", decision.reason)
                return _error_response(403, f"request denied by policy '{decision.policy_name}': {decision.reason}")

        # --- Stage 2: Budget Check ---
        if self.budget_mgr and self.cfg.budget.enabled:
            estimated_cost = calculate_cost(req.model, estimate_tokens(_messages_text(req)), 0)
            allowed, status = self.budget_mgr.check_budget(req_ctx.user_id, req_ctx.team_id, estimated_cost)
            if not allowed:
                self._log_audit(req_ctx, req, None, "budget_exceeded", f"remaining: {status.remaining:.4f}")
                return _error_response(
                    429,
                    f"budget exceeded: daily={status.daily_used:.2f}/{status.daily_limit:.2f}, "
                    f"monthly={status.monthly_used:.2f}/{status.monthly_limit:.2f}",
                )

        # --- Stage 3: Input Guardrails ---
        if self.guardrails and self.cfg.governance.guardrails_enabled:
            input_text = _messages_text(req)
            is_safe, violations = self.guardrails.check_input(input_text)
            if not is_safe:
                if self.metrics:
                    for v in violations:
                        self.metrics.record_guardrail_violation(v.rule)
                self._log_audit(req_ctx, req, None, "guardrail_blocked", violations[0].description)
                return _error_response(400, f"request blocked by guardrails: {violations[0].description}")

        # --- Stage 4: PII Redaction ---
        pii_matches: list[PIIMatch] = []
        if self.pii_redactor and self.cfg.governance.pii_redaction_enabled:
            for i, msg in enumerate(req.messages):
                redacted, matches = self.pii_redactor.redact(msg.content)
                if matches:
                    req.messages[i].content = redacted
                    pii_matches.extend(matches)
                    if self.metrics:
                        for m in matches:
                            self.metrics.record_pii_detection(m.type)

        # --- Stage 5: A/B Test Assignment ---
        if self.ab_tester and self.cfg.ab_testing.enabled and req_ctx.user_id:
            for exp in self.cfg.ab_testing.experiments:
                if exp.enabled:
                    model, group = self.ab_tester.assign(exp.name, req_ctx.user_id)
                    if model:
                        req.model = model
                        req_ctx.ab_test_group = group
                        req_ctx.metadata["ab_experiment"] = exp.name
                        break

        # --- Stage 6: Prompt Compression ---
        if self.compressor and self.cfg.compression.enabled:
            compressed, result = self.compressor.compress(req)
            if result.ratio > 0:
                req = compressed
                req_ctx.metadata["compression_ratio"] = f"{result.ratio:.2f}"
                req_ctx.metadata["original_tokens"] = str(result.original_tokens)

        # --- Stage 7: Plugin pre-processing ---
        if self.plugin_mgr:
            req = await self.plugin_mgr.process_request(req)

        # --- Stage 8: Cache Lookup ---
        if self.cache and self.cfg.cache.enabled and not req.stream:
            cached = await self.cache.get(req)
            if cached is not None:
                req_ctx.cache_hit = True
                if self.metrics:
                    self.metrics.record_cache_hit()
                # Restore PII in cached response
                if self.pii_redactor and pii_matches:
                    for i, choice in enumerate(cached.choices):
                        cached.choices[i].message.content = self.pii_redactor.restore(
                            choice.message.content, pii_matches
                        )
                req_ctx.latency = time.time() - req_ctx.start_time
                self._log_audit(req_ctx, req, cached, "cache_hit", "")
                return JSONResponse(content=cached.model_dump())
            if self.metrics:
                self.metrics.record_cache_miss()

        # --- Stage 9: Route to Provider ---
        try:
            provider = await self.router.route(req)
        except Exception as e:
            return _error_response(502, f"no available provider: {e}")
        req_ctx.provider = provider.name()
        req_ctx.model = req.model

        # --- Stage 10: Execute Request ---
        if req.stream:
            return await self._handle_stream(req_ctx, req, provider, pii_matches)

        start = time.time()
        try:
            resp = await provider.chat_completion(req)
        except GatewayError:
            self.router.record_error(provider.name())
            resp, provider = await self._try_fallback(req, provider.name())
            if resp is None:
                return _error_response(502, "all providers failed")
            req_ctx.provider = provider.name()
        provider_latency = time.time() - start
        self.router.record_latency(provider.name(), provider_latency)

        # --- Stage 11: Output Guardrails ---
        if self.guardrails and self.cfg.governance.guardrails_enabled and resp.choices:
            is_safe, violations = self.guardrails.check_output(resp.choices[0].message.content)
            if not is_safe:
                if self.metrics:
                    for v in violations:
                        self.metrics.record_guardrail_violation(v.rule)
                resp.choices[0].message.content = "[Content filtered by governance policy]"
                req_ctx.metadata["output_filtered"] = "true"

        # --- Stage 12: PII Restoration ---
        if self.pii_redactor and pii_matches:
            for i, choice in enumerate(resp.choices):
                resp.choices[i].message.content = self.pii_redactor.restore(
                    choice.message.content, pii_matches
                )

        # --- Stage 13: Plugin post-processing ---
        if self.plugin_mgr:
            resp = await self.plugin_mgr.process_response(req, resp)

        # --- Cache Store ---
        if self.cache and self.cfg.cache.enabled:
            await self.cache.set(req, resp)

        # --- Record Metrics ---
        if resp.usage.prompt_tokens > 0:
            req_ctx.tokens_in = resp.usage.prompt_tokens
            req_ctx.tokens_out = resp.usage.completion_tokens
        else:
            req_ctx.tokens_in = estimate_tokens(_messages_text(req))
            req_ctx.tokens_out = estimate_tokens(resp.choices[0].message.content) if resp.choices else 0
        req_ctx.cost = calculate_cost(req_ctx.model, req_ctx.tokens_in, req_ctx.tokens_out)
        req_ctx.latency = time.time() - req_ctx.start_time

        if self.metrics:
            self.metrics.record_request(req_ctx)
        if self.budget_mgr and self.cfg.budget.enabled:
            self.budget_mgr.record_usage(req_ctx.user_id, req_ctx.team_id, req_ctx.cost, req_ctx.tokens_in + req_ctx.tokens_out)

        self._log_audit(req_ctx, req, resp, "success", "")
        return JSONResponse(content=resp.model_dump())

    async def _handle_stream(
        self,
        req_ctx: RequestContext,
        req: ChatCompletionRequest,
        provider: BaseProvider,
        pii_matches: list[PIIMatch],
    ) -> StreamingResponse:
        async def _generate():
            total_content = []
            try:
                async for chunk in provider.stream_chat_completion(req):
                    data = json.dumps(chunk.model_dump())
                    yield f"data: {data}\n\n"
                    if chunk.choices and chunk.choices[0].delta.content:
                        total_content.append(chunk.choices[0].delta.content)
            except Exception as e:
                yield f'data: {{"error": "{e}"}}\n\n'
            yield "data: [DONE]\n\n"

            # Record metrics
            req_ctx.tokens_in = estimate_tokens(_messages_text(req))
            req_ctx.tokens_out = estimate_tokens("".join(total_content))
            req_ctx.cost = calculate_cost(req_ctx.model, req_ctx.tokens_in, req_ctx.tokens_out)
            req_ctx.latency = time.time() - req_ctx.start_time
            if self.metrics:
                self.metrics.record_request(req_ctx)

        return StreamingResponse(
            _generate(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Request-ID": req_ctx.request_id,
            },
        )

    async def _try_fallback(
        self, req: ChatCompletionRequest, failed_provider: str
    ) -> tuple[ChatCompletionResponse | None, BaseProvider | None]:
        for name, prov in self.providers.items():
            if name == failed_provider:
                continue
            if req.model in prov.models():
                try:
                    resp = await prov.chat_completion(req)
                    return resp, prov
                except Exception:
                    continue
        return None, None

    def _log_audit(
        self,
        req_ctx: RequestContext,
        req: ChatCompletionRequest,
        resp: ChatCompletionResponse | None,
        status: str,
        reason: str,
    ) -> None:
        if not self.audit_logger or not self.cfg.governance.audit_enabled:
            return
        from .governance.audit import AuditEntry

        metadata = dict(req_ctx.metadata)
        if reason:
            metadata["reason"] = reason
        entry = AuditEntry(
            id=generate_request_id(),
            request_id=req_ctx.request_id,
            user_id=req_ctx.user_id,
            team_id=req_ctx.team_id,
            action="chat_completion",
            model=req_ctx.model,
            provider=req_ctx.provider,
            tokens_in=req_ctx.tokens_in,
            tokens_out=req_ctx.tokens_out,
            cost=req_ctx.cost,
            latency=req_ctx.latency,
            cache_hit=req_ctx.cache_hit,
            status=status,
            metadata=metadata,
        )
        try:
            self.audit_logger.log(entry)
        except Exception as e:
            logger.error("failed to write audit log: %s", e)


def _messages_text(req: ChatCompletionRequest) -> str:
    return " ".join(m.content for m in req.messages)


def _error_response(status: int, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"message": message, "type": "gateway_error", "code": status}},
    )
