# AI Control Plane Gateway (Python)

A drop-in **OpenAI-compatible** API gateway that routes, optimizes, and governs LLM traffic across multiple providers.

Replace `https://api.openai.com/v1` with your gateway URL — no SDK changes needed.

## Features

| Category | Capabilities |
|---|---|
| **Multi-Provider Routing** | OpenAI, Anthropic, Google Gemini, Azure OpenAI, AWS Bedrock, Mistral |
| **6 Routing Strategies** | Round-robin, Weighted, Least-latency, Cost-optimized, Quality-aware, Fallback |
| **Semantic Caching** | LRU cache with TTL, SHA256-based cache keys, configurable max entries |
| **Prompt Compression** | Whitespace trimming, deduplication, history trimming, filler word removal |
| **Circuit Breaker** | Auto-open at >50% error rate, 30s cooldown, half-open probe |
| **Guardrails** | Prompt injection detection, toxic content filtering, output leak prevention |
| **PII Redaction** | SSN, email, credit card, phone, IP, API key detection with reversible masking |
| **Audit Logging** | Immutable JSON-lines files with daily rotation and query support |
| **Policy Engine** | Rule-based access control with 7 operators (eq, neq, gt, lt, in, not_in, matches) |
| **Budget Management** | Per-user and per-team daily/monthly limits with auto-reset |
| **A/B Testing** | Consistent-hash user assignment with result tracking |
| **Observability** | 9 Prometheus metrics, structured logging |
| **Plugin System** | Priority-sorted request/response hooks |

## Quick Start

### Prerequisites

- Python 3.11+

### Install & Run

```bash
# Clone and install
cd gateway-python
pip install -e ".[dev]"

# Set at least one provider key
export OPENAI_API_KEY=sk-...

# Run
python -m src.main

# Or with config file
python -m src.main configs/config.yaml
```

### Docker

```bash
docker build -t ai-control-plane-gateway .
docker run -p 8080:8080 -e OPENAI_API_KEY=sk-... ai-control-plane-gateway
```

### Usage

```bash
# Chat completion (drop-in replacement for OpenAI)
curl http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-4o",
    "messages": [{"role": "user", "content": "Hello!"}]
  }'

# Health check
curl http://localhost:8080/health

# List models
curl http://localhost:8080/v1/models

# Provider stats
curl http://localhost:8080/v1/stats

# Prometheus metrics
curl http://localhost:8080/metrics
```

## Configuration

Configure via YAML file or environment variables:

| Environment Variable | Description |
|---|---|
| `OPENAI_API_KEY` | OpenAI API key |
| `ANTHROPIC_API_KEY` | Anthropic API key |
| `GOOGLE_API_KEY` | Google Gemini API key |
| `MISTRAL_API_KEY` | Mistral API key |
| `GATEWAY_PORT` | Server port (default: 8080) |
| `GATEWAY_CONFIG` | Path to YAML config file |

See [`configs/config.yaml`](configs/config.yaml) for full configuration reference.

## Architecture

```
Client Request
    │
    ▼
┌─────────────────────────────────────────────┐
│  Middleware: CORS → Logging → Auth → Rate   │
│  Limit                                       │
└─────────────────┬───────────────────────────┘
                  │
    ▼ Pipeline (13 stages)
    │
    ├─ 1. Policy evaluation
    ├─ 2. Budget check
    ├─ 3. Input guardrails
    ├─ 4. PII redaction
    ├─ 5. A/B test assignment
    ├─ 6. Prompt compression
    ├─ 7. Plugin pre-processing
    ├─ 8. Cache lookup
    ├─ 9. Route to provider
    ├─ 10. Execute LLM request
    ├─ 11. Output guardrails
    ├─ 12. PII restoration
    └─ 13. Plugin post-processing
              │
              ▼
         Cache store → Metrics → Audit → Response
```

## Development

```bash
make dev        # Install with dev dependencies
make test       # Run tests
make lint       # Lint with ruff
make format     # Auto-format
make typecheck  # Type check with mypy
```

## Project Structure

```
gateway-python/
├── src/
│   ├── main.py              # FastAPI entry point
│   ├── proxy.py             # 13-stage request pipeline
│   ├── router.py            # 6 routing strategies + circuit breaker
│   ├── cache.py             # Semantic LRU cache with TTL
│   ├── compression.py       # Prompt compression
│   ├── abtesting.py         # A/B testing
│   ├── observability.py     # Prometheus metrics
│   ├── budget.py            # Budget management
│   ├── plugin.py            # Plugin system
│   ├── types.py             # Pydantic models
│   ├── config.py            # YAML/env configuration
│   ├── util.py              # Utilities
│   ├── providers/
│   │   ├── base.py          # Abstract provider
│   │   ├── openai.py        # OpenAI
│   │   ├── anthropic.py     # Anthropic Claude
│   │   ├── google.py        # Google Gemini
│   │   ├── azure.py         # Azure OpenAI
│   │   ├── bedrock.py       # AWS Bedrock
│   │   └── mistral.py       # Mistral
│   ├── governance/
│   │   ├── guardrails.py    # Input/output guardrails
│   │   ├── pii.py           # PII redaction
│   │   ├── audit.py         # Audit logging
│   │   └── policy.py        # Policy engine
│   └── middleware/
│       ├── auth.py          # API key authentication
│       ├── rate_limit.py    # Token-bucket rate limiting
│       ├── logging.py       # Request logging
│       └── cors.py          # CORS headers
├── configs/
│   └── config.yaml          # Example configuration
├── tests/
├── pyproject.toml
├── Dockerfile
├── Makefile
└── README.md
```

## License

MIT
