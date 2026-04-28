# AI Control Plane Gateway

> **One endpoint. Every LLM. Full control.**

A production-ready, OpenAI-compatible API gateway that sits between your applications and LLM providers. Drop it in with a single line change — no code rewrites needed.

```
Your App  →  AI Control Plane Gateway  →  OpenAI / Anthropic / Google / 14 more
              (13-stage pipeline)
```

---

## What It Does

Every LLM request passes through a 13-stage pipeline:

```
Request In
    │
    ├─ Stage 1  ── Policy Engine          (model allowlists, token limits, time-of-day rules)
    ├─ Stage 2  ── Budget Enforcement     (per-user and per-team daily/monthly caps)
    ├─ Stage 3  ── Input Guardrails       (prompt injection, jailbreak, blocked topics)
    ├─ Stage 4  ── PHI / PII Redaction    (15 entity types, round-trip restore)
    ├─ Stage 5  ── A/B Test Assignment    (traffic splitting across models)
    ├─ Stage 6  ── Prompt Compression     (trim tokens, deduplicate history)
    ├─ Stage 7  ── Plugin Hooks           (custom pre-processing)
    ├─ Stage 8  ── Semantic Cache         (LRU + TTL, SHA-256 keyed)
    ├─ Stage 9  ── Intelligent Routing    (6 strategies + circuit breaker)
    ├─ Stage 10 ── LLM Execution          (with provider failover)
    ├─ Stage 11 ── Output Guardrails      (clinical hallucination, safety checks)
    ├─ Stage 12 ── PII Restoration        (replace placeholders with real data)
    └─ Stage 13 ── Plugin Hooks           (custom post-processing)
         │
    Response Out
```

---

## Key Features

| Feature | Details |
|---|---|
| **OpenAI-compatible** | Change one line — `base_url` — no SDK changes |
| **17 LLM providers** | OpenAI, Anthropic, Azure, Bedrock, Google, Groq, Mistral, DeepSeek, Cohere, Fireworks, HuggingFace, Ollama, Perplexity, Replicate, Together, xAI, AI21 |
| **PHI / PII redaction** | 15 entity types, round-trip redact → LLM → restore |
| **Semantic caching** | Up to 40% cost reduction on repeated queries |
| **Prompt compression** | Trim redundant tokens before they hit the LLM |
| **Budget caps** | Per-user and per-team daily / monthly limits in USD |
| **6 routing strategies** | Round-robin, weighted, least-latency, cost-optimized, quality, fallback |
| **Circuit breaker** | Auto-failover to next provider on errors |
| **Guardrails** | Prompt injection blocking, 35+ jailbreak patterns, clinical output scanning |
| **Policy engine** | YAML-defined rules: allowlists, token caps, time-of-day |
| **Immutable audit log** | JSONL per-request trail: user, model, tokens, cost, latency |
| **Prometheus metrics** | `/metrics` endpoint — plug into Grafana |
| **A/B testing** | Traffic-split experiments across models with user-level consistency |
| **Plugin system** | Pre/post hooks in pure Python |

---

## Supported Providers

| Provider | Models |
|---|---|
| **OpenAI** | GPT-4o, GPT-4o-mini, GPT-4-turbo, GPT-3.5-turbo |
| **Anthropic** | Claude Opus, Claude Sonnet, Claude Haiku |
| **Azure OpenAI** | All Azure-deployed models |
| **AWS Bedrock** | Titan, Claude on Bedrock |
| **Google** | Gemini 2.0 Flash, Gemini 1.5 Pro/Flash |
| **Groq** | Llama 3.3 70B, Mixtral, Gemma2 |
| **Mistral** | Mistral Large/Medium/Small |
| **DeepSeek** | DeepSeek Chat, DeepSeek Reasoner |
| **Cohere** | Command R+, Command R |
| **Fireworks AI** | Llama, Mixtral (fast inference) |
| **HuggingFace** | Any HF Inference API model |
| **Ollama** | Any locally-served model |
| **Perplexity** | Sonar, Sonar Pro, Sonar Reasoning |
| **Replicate** | Llama, Mistral on Replicate |
| **Together AI** | Llama 3.1 405B, DeepSeek V3 |
| **xAI** | Grok-2 |
| **AI21** | Jamba 1.5 Large/Mini |

---

## Quick Start

### Docker (Recommended)

```bash
# 1. Clone and configure
git clone https://github.com/aaditya-b/ai-control-plane-gateway.git
cd ai-control-plane-gateway
cp .env.example .env
# Edit .env — add your LLM API keys

# 2. Start
docker compose up -d

# 3. Verify
curl http://localhost:8080/health
```

### Python

```bash
pip install -e ".[dev]"
cp .env.example .env        # add your API keys
python -m src.main configs/config.yaml
```

### One-Line Integration

```python
# Before
client = OpenAI(api_key="sk-...")

# After — zero other changes
client = OpenAI(
    api_key="your-gateway-key",
    base_url="http://localhost:8080/v1",
)
```

---

## Configuration

### Minimal Config (`configs/config.yaml`)

```yaml
server:
  port: 8080
  api_keys:
    - "your-secret-key"       # clients send: Authorization: Bearer your-secret-key

providers:
  - name: openai
    api_key: "${OPENAI_API_KEY}"
    base_url: "https://api.openai.com/v1"
    models: [gpt-4o, gpt-4o-mini]

  - name: anthropic
    api_key: "${ANTHROPIC_API_KEY}"
    base_url: "https://api.anthropic.com"
    models: [claude-opus-4-5, claude-sonnet-4-5]

cache:
  enabled: true
  ttl: 300

budget:
  enabled: true
  default_daily_limit: 50.0     # USD per user
  default_monthly_limit: 500.0
```

### Environment Variables

| Variable | Description |
|---|---|
| `OPENAI_API_KEY` | OpenAI API key |
| `ANTHROPIC_API_KEY` | Anthropic API key |
| `GOOGLE_API_KEY` | Google Gemini API key |
| `MISTRAL_API_KEY` | Mistral API key |
| `GROQ_API_KEY` | Groq API key |
| `GATEWAY_API_KEY_1` | Static Bearer token for clients |
| `GATEWAY_API_KEY_2` | Additional client key |
| `GATEWAY_CONFIG` | Path to config YAML |
| `GATEWAY_ENV` | Active environment name (dev/staging/prod) |
| `GRAFANA_ADMIN_PASSWORD` | Grafana dashboard password |

---

## PHI / PII Protection

The gateway redacts sensitive entities before they reach the LLM, then restores them in the response. Clinical staff get coherent answers — the LLM never sees real patient data.

**Before (sent to gateway):**
```
Patient John Smith, MRN 123456789, DOB 03/15/1965,
prescribed Lisinopril by Dr. Sarah Johnson NPI 1234567890, ICD-10: I10
```

**Sent to LLM (redacted):**
```
Patient [NAME_1], MRN [MRN_1], DOB [DATE_1],
prescribed [DRUG_1] by [PROVIDER_1] NPI [NPI_1], ICD-10: [DIAGNOSIS_1]
```

**Returned to caller (restored):**
```
Patient John Smith, MRN 123456789, DOB 03/15/1965,
prescribed Lisinopril by Dr. Sarah Johnson NPI 1234567890, ICD-10: I10
```

**15 entity types detected:** Name · MRN · DOB · SSN · Phone · Email · Address · NPI · DEA · Insurance ID · ICD-10 Code · CPT Code · Drug Name · Provider Name · Date of Service

Enable in config:
```yaml
governance:
  pii_redaction_enabled: true
  pii_healthcare_entities: true   # MRN, NPI, ICD-10, CPT, DEA
  healthcare_mode: true           # clinical hallucination output scanning
```

Custom patterns:
```yaml
governance:
  pii_custom_patterns:
    - ["employee_id", "EMP-\\d{6}", "[EMPLOYEE_ID]"]
    - ["project_code", "PROJ-[A-Z]{4}-\\d{4}", "[PROJECT]"]
```

---

## Routing Strategies

Configure per-route in `configs/config.yaml`:

```yaml
routes:
  - name: default
    strategy: fallback           # primary -> fallback on error
    providers: [openai, anthropic]

  - name: cost-sensitive
    strategy: cost-optimized     # always pick cheapest provider for model
    models: [gpt-4o-mini, claude-haiku]

  - name: high-quality
    strategy: quality            # always pick highest quality-score provider
    providers: [anthropic, openai]
```

| Strategy | Behaviour |
|---|---|
| `round-robin` | Distribute evenly across providers |
| `weighted` | Custom % split (e.g. 70% OpenAI, 30% Azure) |
| `least-latency` | Always route to the fastest provider (EMA tracked) |
| `cost-optimized` | Always pick cheapest token cost for the model |
| `quality` | Always pick highest quality-score provider |
| `fallback` | Primary provider, auto-failover on error |

---

## Budget Management

Per-user and per-team caps with automatic daily/monthly resets:

```yaml
budget:
  enabled: true
  default_daily_limit: 10.0      # USD — applies to all users
  default_monthly_limit: 200.0
  team_budgets:
    radiology: 500.0             # Monthly cap for the radiology team
    oncology: 1000.0
  user_budgets:
    admin@hospital.org: 50.0     # Daily cap for specific users
```

Pass headers with each request:
```
X-User-Id: dr.smith@hospital.org
X-Team-Id: cardiology
```

When a cap is reached, the gateway returns `HTTP 429` before calling the LLM.

---

## Policy Engine

YAML-defined rules evaluated before every request:

```yaml
governance:
  policies:
    - name: model-allowlist
      description: "Only approved models"
      action: deny
      rules:
        - field: model
          operator: not_in
          value: [gpt-4o, gpt-4o-mini, claude-3-5-sonnet]

    - name: token-limit
      description: "Cap max_tokens at 4096"
      action: deny
      rules:
        - field: max_tokens
          operator: gt
          value: 4096
```

---

## Semantic Caching

Identical (or near-identical) requests return cached responses instantly — no LLM call, no cost:

```yaml
cache:
  enabled: true
  ttl: 300              # seconds — cache lifetime
  max_entries: 10000    # LRU eviction when full
  similarity_threshold: 0.95
```

Cache stats available at `GET /v1/stats`.

---

## Alerting

Webhook notifications when thresholds are breached:

```yaml
alerting:
  enabled: true
  webhook_url: "https://hooks.slack.com/services/..."
  email_recipients: ["ops@company.com"]
  smtp_host: "smtp.company.com"
  smtp_port: 587
  smtp_from: "gateway@company.com"
  evaluation_interval: 60   # seconds between checks
```

---

## API Reference

| Endpoint | Method | Description |
|---|---|---|
| `/v1/chat/completions` | POST | OpenAI-compatible chat completions |
| `/chat/completions` | POST | Alias (no `/v1` prefix) |
| `/v1/models` | GET | List all configured models |
| `/v1/stats` | GET | Cache stats, provider stats |
| `/health` | GET | Health check + uptime |
| `/metrics` | GET | Prometheus metrics |
| `/docs` | GET | Swagger UI |

**Request headers:**

| Header | Description |
|---|---|
| `Authorization: Bearer <key>` | Gateway API key |
| `X-User-Id` | User identifier for budget tracking |
| `X-Team-Id` | Team identifier for budget tracking |
| `X-Data-Classification` | `public` / `internal` / `confidential` / `phi` |

---

## Deployment

### Docker Compose (Single Server)

```bash
cp .env.example .env
# Fill in OPENAI_API_KEY, GATEWAY_API_KEY_1, DOMAIN, GRAFANA_ADMIN_PASSWORD
docker compose -f docker-compose.prod.yml up -d
```

Includes: gateway + nginx (TLS) + prometheus + grafana + certbot (Let's Encrypt).

### Kubernetes

```bash
kubectl apply -f k8s/
```

Includes: Deployment, HPA (2-10 replicas), Service, Ingress + cert-manager.

### VPS (Bare Metal)

```bash
pip install -e .
gateway configs/config.yaml
```

---

## Development

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run tests
pytest tests/ -v

# Lint
ruff check src/ tests/

# Type check
mypy src/ --ignore-missing-imports

# Start dev server
python -m src.main configs/config.yaml
```

### Project Structure

```
src/
├── main.py           -> FastAPI app + provider wiring
├── proxy.py          -> 13-stage pipeline
├── router.py         -> 6 routing strategies + circuit breaker
├── cache.py          -> Semantic LRU cache
├── compression.py    -> Prompt compression
├── abtesting.py      -> A/B test assignment
├── budget.py         -> Per-user/team spending caps
├── observability.py  -> Prometheus metrics
├── plugin.py         -> Pre/post hook system
├── config.py         -> YAML + env loader
├── types.py          -> OpenAI-compatible Pydantic models
├── util.py           -> Token estimation, cost table
├── providers/        -> 17 provider adapters
│   ├── base.py       -> BaseProvider + OpenAI-compat base
│   ├── openai.py
│   ├── anthropic.py
│   └── ...           (15 more)
├── governance/
│   ├── guardrails.py -> Prompt injection, jailbreak, topic blocking
│   ├── pii.py        -> PHI/PII redaction + restoration
│   ├── audit.py      -> Immutable JSONL audit log
│   └── policy.py     -> YAML-defined rule engine
└── middleware/
    ├── auth.py        -> Bearer token authentication
    ├── rate_limit.py  -> Per-IP rate limiting
    ├── cors.py        -> CORS headers
    └── logging.py     -> Structured request logging

configs/
├── config.yaml             -> Development configuration
└── config.production.yaml  -> Production template

tests/                      -> pytest test suite
k8s/                        -> Kubernetes manifests
monitoring/                 -> Prometheus + Grafana configs
nginx/                      -> Nginx config (TLS, rate limiting)
```

---

## Security

- **Bearer token auth** — all endpoints require `Authorization: Bearer <key>` (configurable)
- **PHI redaction** — 15 entity types stripped before LLM sees them; restored after
- **Prompt injection blocking** — 35+ jailbreak patterns detected and blocked
- **Immutable audit trail** — every request logged with user, model, cost, outcome
- **Non-root Docker** — container runs as `gateway` user (uid 1000)
- **No secrets in logs** — API keys and tokens are never written to stdout/stderr

---

## License

Apache 2.0 — free to use, modify, and self-host. See [LICENSE](LICENSE).
