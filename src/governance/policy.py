"""Rule-based policy engine for request authorization."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from ..types import ChatCompletionRequest, PolicyConfig, PolicyRule, RequestContext


@dataclass
class Decision:
    """Result of policy evaluation."""

    allowed: bool
    reason: str = ""
    policy_name: str = ""
    warnings: list[str] = field(default_factory=list)


class PolicyEngine:
    """Evaluate requests against an ordered set of policy rules.

    Policies are evaluated in descending priority order.  Within a single
    policy all rules must match (AND logic).  The first matching policy
    determines the outcome via its *action*:

    * ``deny``  -- block the request
    * ``warn``  -- allow but attach a warning
    * ``allow`` -- explicitly permit (short-circuits remaining policies)

    If no policy matches the request is allowed by default.
    """

    def __init__(self, policies: list[PolicyConfig] | None = None) -> None:
        # Sort by priority descending so highest-priority policies evaluate first.
        self._policies: list[PolicyConfig] = sorted(
            policies or [], key=lambda p: p.priority, reverse=True
        )

    def evaluate(
        self,
        req_ctx: RequestContext,
        req: ChatCompletionRequest,
    ) -> Decision:
        """Evaluate *req* in *req_ctx* against all loaded policies."""
        warnings: list[str] = []

        for policy in self._policies:
            if self._policy_matches(policy, req_ctx, req):
                if policy.action == "deny":
                    return Decision(
                        allowed=False,
                        reason=f"Denied by policy '{policy.name}': {policy.description}",
                        policy_name=policy.name,
                        warnings=warnings,
                    )
                if policy.action == "warn":
                    warnings.append(
                        f"Warning from policy '{policy.name}': {policy.description}"
                    )
                    # Continue evaluating remaining policies.
                    continue
                if policy.action == "allow":
                    return Decision(
                        allowed=True,
                        reason=f"Explicitly allowed by policy '{policy.name}'",
                        policy_name=policy.name,
                        warnings=warnings,
                    )

        # Default: allow when no deny policy matched.
        return Decision(allowed=True, reason="default_allow", warnings=warnings)

    # ── Internal helpers ────────────────────────────────────────────

    def _policy_matches(
        self,
        policy: PolicyConfig,
        req_ctx: RequestContext,
        req: ChatCompletionRequest,
    ) -> bool:
        """Return True if every rule in *policy* matches (AND logic)."""
        for rule in policy.rules:
            if not self._evaluate_rule(rule, req_ctx, req):
                return False
        return True

    def _evaluate_rule(
        self,
        rule: PolicyRule,
        req_ctx: RequestContext,
        req: ChatCompletionRequest,
    ) -> bool:
        """Evaluate a single rule against the request context and request."""
        field_value = self._extract_field(rule.field, req_ctx, req)
        return self._apply_operator(rule.operator, field_value, rule.value)

    # ── Field extraction ────────────────────────────────────────────

    @staticmethod
    def _extract_field(
        field_name: str,
        req_ctx: RequestContext,
        req: ChatCompletionRequest,
    ) -> Any:
        """Extract a named field value from the request or context."""
        if field_name == "model":
            return req.model
        if field_name == "user":
            return req_ctx.user_id
        if field_name == "team":
            return req_ctx.team_id
        if field_name == "max_tokens":
            return req.max_tokens or 0
        if field_name == "hour":
            return datetime.now(timezone.utc).hour
        if field_name == "day":
            return datetime.now(timezone.utc).strftime("%A").lower()
        if field_name == "message_count":
            return len(req.messages)

        # Dotted metadata access: metadata.key
        if field_name.startswith("metadata."):
            key = field_name[len("metadata."):]
            return req_ctx.metadata.get(key, "")

        return None

    # ── Operator evaluation ─────────────────────────────────────────

    @staticmethod
    def _apply_operator(operator: str, field_value: Any, rule_value: Any) -> bool:
        """Compare *field_value* against *rule_value* using *operator*."""
        if operator == "eq":
            return field_value == rule_value
        if operator == "neq":
            return field_value != rule_value
        if operator == "gt":
            try:
                return float(field_value) > float(rule_value)
            except (TypeError, ValueError):
                return False
        if operator == "lt":
            try:
                return float(field_value) < float(rule_value)
            except (TypeError, ValueError):
                return False
        if operator == "in":
            if isinstance(rule_value, list):
                return field_value in rule_value
            return str(field_value) in str(rule_value)
        if operator == "not_in":
            if isinstance(rule_value, list):
                return field_value not in rule_value
            return str(field_value) not in str(rule_value)
        if operator == "matches":
            try:
                return bool(re.search(str(rule_value), str(field_value)))
            except re.error:
                return False
        return False
