# AI Control Plane Gateway

**A drop-in OpenAI-compatible API gateway that routes, optimizes, and governs LLM traffic across 17 providers.**

Point your existing OpenAI SDK at the gateway URL — no SDK changes, no prompt rewrites. In return you get intelligent routing, semantic caching, prompt compression, cost controls, guardrails, PII redaction, audit logging, budgets, A/B testing, and Prometheus metrics.

```diff
- https://api.openai.com/v1
+ http://your-gateway:8080/v1
```

---

## Table of Contents

1. [Why a Gateway?](#why-a-gateway)
2. [Supported Providers](#supported-providers)
3. [Architecture & Request Pipeline](#architecture--request-pipeline)
4. [Feature Reference](#feature-reference)
   - [Multi-Provider Routing](#1-multi-provider-routing)
   - [Routing Strategies](#2-routing-strategies)
   - [Circuit Breaker & Fallback](#3-circuit-breaker--fallback)
   - [Semantic Caching](#4-semantic-caching)
   - [Prompt Compression](#5-prompt-compression)
   - [Guardrails](#6-guardrails)
   - [PII Redaction](#7-pii-redaction)
   - [Policy Engine](#8-policy-engine)
   - [Budget Management](#9-budget-management)
   - [A/B Testing](#10-ab-testing)
   - [Audit Logging](#11-audit-logging)
   - [Observability](#12-observability)
   - [Plugin System](#13-plugin-system)
   - [Authentication & Rate Limiting](#14-authentication--rate-limiting)
5. [Installation](#installation)
6. [Quick Start](#quick-start)
7. [Configuration Reference](#configuration-reference)
8. [HTTP API](#http-api)
9. [Client Examples](#client-examples)
10. [Docker Deployment](#docker-deployment)
11. [Development](#development)
12. [Project Structure](#project-structure)
13. [Troubleshooting](#troubleshooting)
14. [License](#license)

---

## Why a Gateway?

Calling LLMs directly from application code gets painful fast:

- You hard-code a single provider and can't shop for price, latency, or quality.
- A provider outage means a product outage.
- Every team re-implements caching, retries, budgets, and PII scrubbing.
- Finance can't answer "how much did we spend per team last month?"
- Security can't answer "did any prompt contain a credit-card number?"

This gateway centralises those concerns behind the same OpenAI-compatible endpoint your code already speaks. Your app sees `/v1/chat/completions`; the gateway handles everything behind it.

## Supported Providers

The gateway supports **17 providers** out of the box. Any of them can be configured independently; you only need API keys for the ones you actually want to use.

| Provider | Identifier(s) | Notable Models | Format |
|---|---|---|---|
| OpenAI | `openai` | GPT-4o, GPT-4 Turbo, GPT-3.5 Turbo | Native OpenAI |
| Anthropic | `anthropic` | Claude 3 Opus, 3.5 Sonnet, 3 Haiku | Custom (Messages API) |
| Google Gemini | `google`, `gemini` | Gemini 1.5 Pro, 1.5 Flash | Custom |
| Azure OpenAI | `azure` | Deployment-scoped GPT models | Native OpenAI |
| AWS Bedrock | `bedrock` | Claude, Titan, Llama on AWS | Custom (SigV4) |
| Mistral | `mistral` | Mistral Large / Medium / Small | OpenAI-compatible |
| Groq | `groq` | Llama 3.3 70B, Mixtral, Gemma2 (ultra-fast) | OpenAI-compatible |
| Together AI | `together`, `togetherai` | Llama 3.3 Turbo, DeepSeek V3, Qwen | OpenAI-compatible |
| DeepSeek | `deepseek` | DeepSeek V3 (`deepseek-chat`), R1 (`deepseek-reasoner`) | OpenAI-compatible |
| xAI | `xai`, `grok` | Grok 2, Grok Beta | OpenAI-compatible |
| Perplexity | `perplexity`, `pplx` | Sonar, Sonar Pro, Sonar Reasoning | OpenAI-compatible |
| Fireworks AI | `fireworks` | Llama 3.3 70B, Mixtral (fast hosting) | OpenAI-compatible |
| Cohere | `cohere` | Command R, Command R+ | Custom (v2/chat) |
| AI21 Labs | `ai21` | Jamba 1.5 Large / Mini | OpenAI-compatible |
| HuggingFace | `huggingface`, `hf` | Any Serverless Inference model | OpenAI-compatible (per-model URL) |
| Replicate | `replicate` | Llama, Mixtral via prediction API | Custom (sync predictions) |
| Ollama | `ollama` | Local Llama, Mistral, Qwen, DeepSeek-R1 | OpenAI-compatible |

All providers emit the **same OpenAI-compatible response shape**, so clients don't know (or care) which provider served a request.

## Architecture & Request Pipeline

```
Client
  │  POST /v1/chat/completions
  ▼
┌──────────────────────────────────────────────────┐
│  Middleware:  CORS → Logging → Auth → Rate Limit │
└──────────────────────┬───────────────────────────┘
                       ▼
┌───────────────────────────────────────────────────────┐
│                   Proxy Pipeline                      │
│  1.  Policy evaluation       (allow/deny/warn rules)  │
│  2.  Budget check            (user/team spend caps)   │
│  3.  Input guardrails        (prompt-injection, tox)  │
│  4.  PII redaction           (SSN, email, CC, keys)   │
│  5.  A/B test assignment     (consistent-hash)        │
│  6.  Prompt compression      (trim / dedupe history)  │
│  7.  Plugin pre-processing                            │
│  8.  Cache lookup            (SHA256 → response)      │
│  9.  Route to provider       (6 strategies)           │
│ 10.  Execute upstream call   (with retries + CB)      │
│ 11.  Output guardrails                                │
│ 12.  PII restoration                                  │
│ 13.  Plugin post-processing                           │
│      Cache store → Metrics → Audit → Response         │
└───────────────────────────────────────────────────────┘
```

Every stage is **independently toggleable** from config — you can run the gateway as pure routing, or with the full governance stack, or anything in between.

## Feature Reference

### 1. Multi-Provider Routing

Configure any subset of the 17 providers under `providers:` in `config.yaml`. Each entry carries its own API key, base URL, model list, timeout, and retry policy:

```yaml
providers:
  - name: openai
    api_key: "${OPENAI_API_KEY}"
    models: [gpt-4o, gpt-4o-mini]
    timeout: 30.0
    max_retries: 3
  - name: anthropic
    api_key: "${ANTHROPIC_API_KEY}"
    models: [claude-3-5-sonnet, claude-3-haiku]
```

`${VAR}` expressions are resolved from environment variables at load time, so real secrets never live in the config file.

### 2. Routing Strategies

Define one or more `routes` that match on model name and choose a `strategy`:

| Strategy | Behaviour |
|---|---|
| `round-robin` | Distribute evenly across eligible providers |
| `weighted` | Random selection weighted by `weights:` map |
| `least-latency` | Pick the provider with the lowest observed rolling-average latency |
| `cost-optimized` | Pick the cheapest provider per `cost_per_token:` |
| `quality` | Pick the highest-scoring provider per `quality_scores:` |
| `fallback` | Try providers in declared order; fail over on error |

Routes are **scoped by model** — a `premium` route can target only `gpt-4o` / `claude-3-opus`, while a `cost-sensitive` route covers the mini/haiku/flash tier. The first matching route wins.

```yaml
routes:
  - name: cost-sensitive
    strategy: cost-optimized
    models: [gpt-4o-mini, claude-3-haiku, gemini-1.5-flash]
    cost_per_token:
      openai: 0.00015
      anthropic: 0.00025
      google: 0.00035
```

### 3. Circuit Breaker & Fallback

Every provider has an independent circuit breaker (`src/router.py`):

- Tracks rolling error rate and latency.
- **Opens** when error rate exceeds 50% after at least 10 requests.
- Stays open for a 30 s cooldown, then half-opens and admits one probe request.
- Closes automatically on success.

On top of the breaker, the proxy applies **automatic fallback**: if the primary provider raises an error for a given request, the gateway walks the remaining configured providers that advertise the requested model and retries transparently.

### 4. Semantic Caching

An in-process LRU cache with TTL returns previously-seen responses without an upstream call:

- Cache key = SHA-256 of the normalised request (model + messages + sampling params).
- Default TTL: 300 s; default capacity: 10,000 entries.
- Disabled automatically for `stream: true` requests.
- PII is restored in cached responses (see §7) so cached entries stay clean even for personalised traffic.

```yaml
cache:
  enabled: true
  ttl: 300
  max_entries: 10000
  similarity_threshold: 0.95
```

`GET /v1/stats` exposes per-cache hit/miss counters.

### 5. Prompt Compression

Reduces token count before the upstream call (`src/compression.py`):

- Trims leading/trailing whitespace and collapses runs of blank lines.
- Deduplicates identical consecutive messages.
- Truncates conversation history to `max_history_messages` (oldest first).
- Only fires when input exceeds `min_tokens`.

Each compression is recorded in `req_ctx.metadata` (`compression_ratio`, `original_tokens`) so you can measure savings in audit logs.

### 6. Guardrails

Input and output content is scanned (`src/governance/guardrails.py`) against two lists:

- `blocked_patterns`: regular-expression patterns that, if matched, cause a 400 rejection with the violation description.
- `blocked_topics`: simple substring topic matches.

Output guardrails replace flagged responses with `"[Content filtered by governance policy]"` and flag the audit record. Both input and output violations increment `gateway_guardrail_violations_total`.

### 7. PII Redaction

Six detectors run over every inbound message (`src/governance/pii.py`):

| Type | Example input | Replacement |
|---|---|---|
| SSN | `123-45-6789` | `[SSN_REDACTED]` |
| Email | `alice@example.com` | `[EMAIL_REDACTED]` |
| Credit card | `4111-1111-1111-1111` | `[CC_REDACTED]` |
| Phone | `+1 (415) 555-1234` | `[PHONE_REDACTED]` |
| IP address | `192.168.1.42` | `[IP_REDACTED]` |
| API key | `sk-...`, `AKIA...`, `ghp_...`, `xox[bpras]-...` | `[API_KEY_REDACTED]` |

Detected matches are kept in request-scoped memory and **restored in the response** before returning to the client — upstream never sees the original PII, but the user sees a coherent reply. Detections emit `gateway_pii_detections_total`.

### 8. Policy Engine

Declarative, priority-sorted rules evaluated before the upstream call (`src/governance/policy.py`):

```yaml
policies:
  - name: model-allowlist
    action: deny
    priority: 100
    rules:
      - field: model
        operator: not_in
        value: [gpt-4o, claude-3-5-sonnet]
  - name: token-cap
    action: deny
    priority: 90
    rules:
      - { field: max_tokens, operator: gt, value: 8192 }
  - name: off-hours
    action: warn
    priority: 10
    rules:
      - { field: hour, operator: gt, value: 22 }
```

Supported operators: `eq`, `neq`, `gt`, `lt`, `in`, `not_in`, `matches` (regex). Supported fields include `model`, `max_tokens`, `temperature`, `user_id`, `team_id`, and `hour` (server local). Highest-priority matching rule wins.

### 9. Budget Management

Per-user and per-team spending caps with daily and monthly reset windows (`src/budget.py`):

```yaml
budget:
  enabled: true
  default_daily_limit: 100.0       # USD
  default_monthly_limit: 2000.0
  team_budgets:
    research: 500.0
    marketing: 100.0
  user_budgets:
    u_12345: 25.0
```

The proxy estimates the cost of each request before dispatch and denies with HTTP 429 if it would exceed the remaining budget. Actual recorded cost (from real token counts) updates the running totals after completion. Pricing is looked up in `src/util.py::_MODEL_PRICING`, which ships with rates for 40+ models across all providers (Ollama/local models are priced at 0).

The caller identifies themselves with optional headers:

```
X-User-Id: alice@example.com
X-Team-Id: research
```

### 10. A/B Testing

Consistent-hash user assignment (`src/abtesting.py`) lets you compare models on live traffic:

```yaml
ab_testing:
  enabled: true
  experiments:
    - name: gpt4o-vs-claude
      models: [gpt-4o, claude-3-5-sonnet]
      traffic_split: [0.5, 0.5]
      enabled: true
```

The same `X-User-Id` always routes to the same variant, so users see stable behaviour. The assigned group is recorded in audit logs and metrics for downstream analysis.

### 11. Audit Logging

Every request produces one append-only JSON-lines record (`src/governance/audit.py`) with:

- request id, user id, team id, action, model, provider
- prompt and completion tokens, computed cost (USD), wall-clock latency
- cache hit, A/B group, compression ratio, PII detection counts
- status (`success`, `policy_denied`, `budget_exceeded`, `guardrail_blocked`, `cache_hit`) and reason

Files rotate daily under `audit_storage_path` (default `./audit_logs/`) and are safe to ship to any log pipeline (Splunk, Datadog, S3, BigQuery).

### 12. Observability

Nine Prometheus metrics are exposed at `/metrics` (`src/observability.py`):

| Metric | Type | Labels |
|---|---|---|
| `gateway_requests_total` | counter | provider, model, status |
| `gateway_request_duration_seconds` | histogram | — |
| `gateway_tokens_total` | counter | provider, model, direction (input/output) |
| `gateway_cost_dollars_total` | counter | — |
| `gateway_cache_hits_total` | counter | — |
| `gateway_cache_misses_total` | counter | — |
| `gateway_guardrail_violations_total` | counter | — |
| `gateway_pii_detections_total` | counter | — |
| `gateway_active_requests` | gauge | — |

Combined with structured logs (set `observability.log_level: debug` for verbose), this gives you per-team cost attribution, SLO dashboards, and cache effectiveness in one place.

### 13. Plugin System

`src/plugin.py` provides priority-sorted `on_request` / `on_response` hooks. A plugin is any object with those coroutine methods:

```python
class LoggingPlugin:
    priority = 10
    async def on_request(self, req):   # mutate or observe
        return req
    async def on_response(self, req, resp):
        return resp
```

Register plugins in code via `PluginManager.register()`. Useful for: injecting system prompts, custom rate-limit dimensions, redaction for company-specific secret formats, response reranking, response caching into external stores, etc.

### 14. Authentication & Rate Limiting

- **Auth** (`src/middleware/auth.py`): if `server.api_keys` is non-empty, each request must present a matching `Authorization: Bearer <key>` header.
- **Rate limit** (`src/middleware/rate_limit.py`): token-bucket limiter keyed on the authenticated API key (or client IP as a fallback).
- **CORS** (`src/middleware/cors.py`): permissive by default; override in code if needed.
- **Request logging** (`src/middleware/logging.py`): logs method, path, status, and latency with the gateway-assigned `X-Request-Id`.

## Installation

### Prerequisites

- **Python 3.11+** (`pyproject.toml` requires `>=3.11`; we use PEP 604 `X | None` types).
- One or more provider API keys.

### From source

```bash
git clone <this-repo>
cd gateway-python
pip install -e ".[dev]"    # dev extras include pytest, ruff, mypy
```

Or with Make:

```bash
make dev       # editable install + dev deps
make run       # start the server using configs/config.yaml
make test      # run pytest
make lint      # ruff check
make format    # ruff format
make typecheck # mypy src/
make docker    # build Docker image
```

## Quick Start

### Zero-config (env-driven)

Set at least one provider key and run:

```bash
export OPENAI_API_KEY=sk-...
python -m src.main
```

The gateway auto-discovers providers from standard `*_API_KEY` environment variables (OpenAI, Anthropic, Google, Mistral) and starts on port 8080 with sensible defaults.

### Full configuration

```bash
export OPENAI_API_KEY=sk-...
export ANTHROPIC_API_KEY=sk-ant-...
export GROQ_API_KEY=gsk_...
export DEEPSEEK_API_KEY=sk-...
# ... etc.

python -m src.main configs/config.yaml
# or
GATEWAY_CONFIG=configs/config.yaml python -m src.main
```

### Send a chat completion

```bash
curl http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "X-User-Id: alice" \
  -H "X-Team-Id: research" \
  -d '{
    "model": "gpt-4o",
    "messages": [{"role": "user", "content": "Summarise CAP theorem in one sentence."}]
  }'
```

### Stream

```bash
curl -N http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "claude-3-5-sonnet",
    "messages": [{"role": "user", "content": "Count 1 to 5."}],
    "stream": true
  }'
```

## Configuration Reference

All configuration lives in a single YAML file. A fully-annotated example is in [`configs/config.yaml`](configs/config.yaml); the top-level sections are:

```yaml
server: { port, host, workers, api_keys[] }
providers: [ {name, api_key, base_url, models[], timeout, max_retries} ]
routes:    [ {name, strategy, models[], providers[], weights{}, cost_per_token{}, quality_scores{}} ]
cache:         { enabled, ttl, max_entries, similarity_threshold }
compression:   { enabled, target_ratio, min_tokens, max_history_messages, remove_duplicates, trim_whitespace }
observability: { metrics_enabled, tracing_enabled, log_level }
governance:    { guardrails_enabled, pii_redaction_enabled, audit_enabled, policy_enabled,
                 audit_storage_path, blocked_patterns[], blocked_topics[], policies[] }
budget:        { enabled, default_daily_limit, default_monthly_limit, team_budgets{}, user_budgets{} }
ab_testing:    { enabled, experiments[] }
```

### Environment variables

| Variable | Purpose |
|---|---|
| `GATEWAY_CONFIG` | Path to YAML config file |
| `GATEWAY_PORT` | Override `server.port` |
| `OPENAI_API_KEY` | OpenAI |
| `ANTHROPIC_API_KEY` | Anthropic |
| `GOOGLE_API_KEY` | Google Gemini |
| `MISTRAL_API_KEY` | Mistral |
| `GROQ_API_KEY` | Groq |
| `TOGETHER_API_KEY` | Together AI |
| `DEEPSEEK_API_KEY` | DeepSeek |
| `XAI_API_KEY` | xAI (Grok) |
| `PERPLEXITY_API_KEY` | Perplexity |
| `FIREWORKS_API_KEY` | Fireworks AI |
| `COHERE_API_KEY` | Cohere |
| `AI21_API_KEY` | AI21 Labs |
| `HF_API_KEY` | HuggingFace |
| `REPLICATE_API_TOKEN` | Replicate |
| `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT` | Azure OpenAI |
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION` | AWS Bedrock |

Any `${VAR}` expression in `config.yaml` is interpolated from the environment at load time.

## HTTP API

| Method | Path | Purpose |
|---|---|---|
| POST | `/v1/chat/completions` | OpenAI-compatible chat completion (supports `stream: true`) |
| POST | `/chat/completions` | Alias (no version prefix) |
| GET  | `/v1/models` | List of every model across all configured providers |
| GET  | `/health` | Liveness / version / uptime / provider count |
| GET  | `/v1/stats` | Provider state + cache hit/miss counters |
| GET  | `/metrics` | Prometheus scrape endpoint (if `metrics_enabled: true`) |
| GET  | `/docs` | FastAPI interactive Swagger UI |

The request / response body for `/v1/chat/completions` follows the OpenAI schema exactly (`model`, `messages`, `temperature`, `max_tokens`, `top_p`, `stream`, `stop`, `presence_penalty`, `frequency_penalty`, `user`, `tools`, `tool_choice`). Responses carry `id`, `model`, `choices[]`, and `usage`. Streaming uses Server-Sent Events with `data: ...\n\n` framing terminated by `data: [DONE]\n\n`.

## Client Examples

### Python (OpenAI SDK)

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8080/v1",
    api_key="not-needed-unless-server.api_keys-is-set",
    default_headers={"X-User-Id": "alice", "X-Team-Id": "research"},
)

resp = client.chat.completions.create(
    model="claude-3-5-sonnet",   # route through the gateway to Anthropic
    messages=[{"role": "user", "content": "Hello!"}],
)
print(resp.choices[0].message.content)
```

### TypeScript / Node

```ts
import OpenAI from "openai";
const openai = new OpenAI({
  baseURL: "http://localhost:8080/v1",
  apiKey: "sk-gateway",
  defaultHeaders: { "X-User-Id": "bob" },
});
const resp = await openai.chat.completions.create({
  model: "llama-3.3-70b-versatile",   // routed to Groq
  messages: [{ role: "user", content: "Hi" }],
});
```

### curl

```bash
curl http://localhost:8080/v1/chat/completions \
  -H "Authorization: Bearer $GATEWAY_KEY" \
  -H "Content-Type: application/json" \
  -d '{ "model": "deepseek-chat", "messages": [{"role":"user","content":"Hello"}] }'
```

## Docker Deployment

```bash
docker build -t ai-control-plane-gateway .

docker run -d --name gateway \
  -p 8080:8080 \
  -e OPENAI_API_KEY=sk-... \
  -e ANTHROPIC_API_KEY=sk-ant-... \
  -e GROQ_API_KEY=gsk_... \
  -v $(pwd)/configs:/app/configs \
  -v $(pwd)/audit_logs:/app/audit_logs \
  ai-control-plane-gateway
```

The image uses `python:3.12-slim`, installs dependencies from `pyproject.toml`, and runs `python -m src.main` with `GATEWAY_CONFIG=configs/config.yaml`. For Kubernetes, a sidecar Prometheus scrape annotation `prometheus.io/port: "8080"`, `prometheus.io/path: "/metrics"` is sufficient.

## Development

```bash
make dev        # editable install + pytest/ruff/mypy
make test       # pytest tests/ -v
make lint       # ruff check src/ tests/
make format     # ruff format src/ tests/
make typecheck  # mypy src/
make run        # python -m src.main configs/config.yaml
make docker     # build image
make clean      # drop caches, build artefacts
```

### Adding a new provider

1. If the provider is OpenAI-compatible, create `src/providers/newprov.py`:

   ```python
   from .openai_compat import OpenAICompatibleProvider

   class NewProvProvider(OpenAICompatibleProvider):
       PROVIDER_NAME = "newprov"
       DEFAULT_BASE_URL = "https://api.newprov.com/v1"
       DEFAULT_MODELS = ["newprov-large", "newprov-small"]
   ```

2. For a custom schema, subclass `BaseProvider` directly (see `cohere.py` or `replicate.py` for examples of response parsing and streaming-SSE handling).
3. Register the class in `src/providers/__init__.py` and `src/main.py::_PROVIDER_MAP`.
4. Add pricing to `src/util.py::_MODEL_PRICING`.
5. Add a sample entry to `configs/config.yaml`.

## Project Structure

```
gateway-python/
├── src/
│   ├── main.py                 # FastAPI entry point, provider wiring
│   ├── proxy.py                # 13-stage request pipeline
│   ├── router.py               # 6 strategies + circuit breaker
│   ├── cache.py                # LRU cache with TTL
│   ├── compression.py          # Prompt compression
│   ├── abtesting.py            # Consistent-hash A/B assignment
│   ├── budget.py               # Per-user / per-team budgets
│   ├── observability.py        # Prometheus metrics
│   ├── plugin.py               # Plugin manager with priority hooks
│   ├── config.py               # YAML + env loader, Pydantic schema
│   ├── types.py                # OpenAI-compatible Pydantic models
│   ├── util.py                 # Token estimate, cost table, hashing
│   ├── providers/
│   │   ├── base.py             # Abstract provider, retries, SSE stream
│   │   ├── openai_compat.py    # Shared OpenAI-compatible base class
│   │   ├── openai.py           # OpenAI
│   │   ├── anthropic.py        # Anthropic (Messages API)
│   │   ├── google.py           # Google Gemini
│   │   ├── azure.py            # Azure OpenAI
│   │   ├── bedrock.py          # AWS Bedrock (SigV4)
│   │   ├── mistral.py          # Mistral
│   │   ├── groq.py             # Groq
│   │   ├── together.py         # Together AI
│   │   ├── deepseek.py         # DeepSeek V3 / R1
│   │   ├── xai.py              # xAI Grok
│   │   ├── perplexity.py       # Perplexity Sonar
│   │   ├── fireworks.py        # Fireworks AI
│   │   ├── ollama.py           # Ollama (local)
│   │   ├── cohere.py           # Cohere v2/chat
│   │   ├── ai21.py             # AI21 Jamba
│   │   ├── huggingface.py      # HuggingFace Inference API
│   │   └── replicate.py        # Replicate predictions
│   ├── governance/
│   │   ├── guardrails.py       # Input / output content filters
│   │   ├── pii.py              # PII detection + reversible redaction
│   │   ├── audit.py            # JSON-lines audit logger (daily rotation)
│   │   └── policy.py           # Rule-based policy engine
│   └── middleware/
│       ├── auth.py             # Bearer-token auth
│       ├── rate_limit.py       # Token-bucket limiter
│       ├── logging.py          # Request log formatter
│       └── cors.py             # CORS headers
├── configs/
│   └── config.yaml             # Fully-annotated example config
├── tests/                      # Pytest suite
├── pyproject.toml              # Dependencies, tooling config
├── Dockerfile                  # Slim container image
├── Makefile                    # dev / test / lint / run / docker targets
└── README.md                   # (this file)
```

## Troubleshooting

**"no route configured for model X"** — the model name doesn't match any `routes[].models[]`. Add `"*"` to a catch-all route, or list the model explicitly.

**"all providers are circuit-open"** — every configured provider has tripped its breaker. Check upstream health; the breaker auto-closes after 30 s.

**"budget exceeded"** — the caller's `X-User-Id` / `X-Team-Id` has hit its daily or monthly cap. Raise the limit in config or wait for the reset window.

**"request denied by policy 'X'"** — a `deny` policy matched. The error message includes the policy name; check `config.yaml::governance.policies`.

**403 with empty body** — auth middleware rejected the request. Set `Authorization: Bearer <key>` where `<key>` is in `server.api_keys`.

**Prometheus endpoint returns 404** — set `observability.metrics_enabled: true`.

**Streaming response is buffered in curl** — use `curl -N` to disable output buffering.

**"unknown provider 'X', skipping"** — the `name:` in your provider entry isn't in `_PROVIDER_MAP`. Check spelling; aliases like `gemini`, `grok`, `hf`, `pplx` are accepted.

## License

Apache-2.0. See `pyproject.toml` for the canonical declaration.
