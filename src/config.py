"""Configuration loading from YAML and environment variables."""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from .types import ExperimentConfig, PolicyConfig, ProviderConfig, RouteConfig


class ServerConfig(BaseModel):
    port: int = 8080
    host: str = "0.0.0.0"
    workers: int = 1
    api_keys: list[str] = Field(default_factory=list)


class CacheConfig(BaseModel):
    enabled: bool = True
    ttl: float = 300.0  # seconds
    max_entries: int = 10000
    similarity_threshold: float = 0.95


class CompressionConfig(BaseModel):
    enabled: bool = True
    target_ratio: float = 0.3
    min_tokens: int = 100
    max_history_messages: int = 20
    remove_duplicates: bool = True
    trim_whitespace: bool = True


class ObservabilityConfig(BaseModel):
    metrics_enabled: bool = True
    log_level: str = "info"


class AlertingConfig(BaseModel):
    enabled: bool = False
    webhook_url: str = ""
    email_recipients: list[str] = Field(default_factory=list)
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_from: str = ""
    smtp_username: str = ""
    smtp_password: str = ""
    evaluation_interval: int = 60


class DataResidencyConfig(BaseModel):
    enabled: bool = False
    # Provider names approved for PHI/confidential traffic
    approved_phi_providers: list[str] = Field(default_factory=list)
    # Approved cloud regions (substring match on provider base_url)
    approved_regions: list[str] = Field(
        default_factory=lambda: ["eastus", "eastus2", "westus", "westus2", "centralus"]
    )


class GovernanceConfig(BaseModel):
    guardrails_enabled: bool = True
    healthcare_mode: bool = False          # enables clinical-hallucination output checks
    pii_redaction_enabled: bool = True
    pii_healthcare_entities: bool = True   # MRN, ICD-10, CPT, NPI, DOB, DEA
    # Caller-supplied extra PII patterns: [[name, regex, replacement], ...]
    pii_custom_patterns: list[list[str]] = Field(default_factory=list)
    audit_enabled: bool = True
    policy_enabled: bool = True
    audit_storage_path: str = "./audit_logs"
    blocked_patterns: list[str] = Field(default_factory=list)
    blocked_topics: list[str] = Field(default_factory=list)
    policies: list[PolicyConfig] = Field(default_factory=list)
    data_residency: DataResidencyConfig = Field(default_factory=DataResidencyConfig)


class BudgetConfig(BaseModel):
    enabled: bool = True
    default_daily_limit: float = 100.0
    default_monthly_limit: float = 2000.0
    team_budgets: dict[str, float] = Field(default_factory=dict)
    user_budgets: dict[str, float] = Field(default_factory=dict)


class ABTestingConfig(BaseModel):
    enabled: bool = False
    experiments: list[ExperimentConfig] = Field(default_factory=list)


class EnvironmentConfig(BaseModel):
    """Override providers and routes for a named deployment environment."""
    name: str
    providers: list[ProviderConfig] = Field(default_factory=list)
    routes: list[RouteConfig] = Field(default_factory=list)


class GatewayConfig(BaseModel):
    server: ServerConfig = Field(default_factory=ServerConfig)
    providers: list[ProviderConfig] = Field(default_factory=list)
    routes: list[RouteConfig] = Field(default_factory=list)
    cache: CacheConfig = Field(default_factory=CacheConfig)
    compression: CompressionConfig = Field(default_factory=CompressionConfig)
    observability: ObservabilityConfig = Field(default_factory=ObservabilityConfig)
    governance: GovernanceConfig = Field(default_factory=GovernanceConfig)
    budget: BudgetConfig = Field(default_factory=BudgetConfig)
    ab_testing: ABTestingConfig = Field(default_factory=ABTestingConfig)
    alerting: AlertingConfig = Field(default_factory=AlertingConfig)
    # Named environment overrides — selected via GATEWAY_ENV env var
    environments: list[EnvironmentConfig] = Field(default_factory=list)


# ── Loaders ──────────────────────────────────────────────────────────────────

def load_config(path: str | Path | None = None) -> GatewayConfig:
    """Load configuration from a YAML file, falling back to environment variables."""
    if path and Path(path).exists():
        with open(path) as f:
            raw = yaml.safe_load(f) or {}
        cfg = GatewayConfig(**raw)
    else:
        cfg = _load_from_env()

    # Apply per-environment overrides
    env_name = os.getenv("GATEWAY_ENV", "").strip()
    if env_name:
        for env_block in cfg.environments:
            if env_block.name == env_name:
                if env_block.providers:
                    cfg.providers = env_block.providers
                if env_block.routes:
                    cfg.routes = env_block.routes
                break

    return cfg


def _load_from_env() -> GatewayConfig:
    cfg = GatewayConfig()

    port = os.getenv("GATEWAY_PORT")
    if port:
        cfg.server.port = int(port)

    if key := os.getenv("OPENAI_API_KEY"):
        cfg.providers.append(ProviderConfig(
            name="openai", api_key=key, base_url="https://api.openai.com/v1",
            models=["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-3.5-turbo"],
        ))

    if key := os.getenv("ANTHROPIC_API_KEY"):
        cfg.providers.append(ProviderConfig(
            name="anthropic", api_key=key, base_url="https://api.anthropic.com",
            models=["claude-opus-4-5", "claude-sonnet-4-5", "claude-3-5-haiku"],
        ))

    if key := os.getenv("GOOGLE_API_KEY"):
        cfg.providers.append(ProviderConfig(
            name="google", api_key=key,
            base_url="https://generativelanguage.googleapis.com",
            models=["gemini-2.0-flash", "gemini-1.5-pro", "gemini-1.5-flash"],
        ))

    if key := os.getenv("MISTRAL_API_KEY"):
        cfg.providers.append(ProviderConfig(
            name="mistral", api_key=key, base_url="https://api.mistral.ai/v1",
            models=["mistral-large-latest", "mistral-medium-latest", "mistral-small-latest"],
        ))

    if webhook := os.getenv("GATEWAY_ALERT_WEBHOOK"):
        cfg.alerting.enabled = True
        cfg.alerting.webhook_url = webhook

    return cfg
