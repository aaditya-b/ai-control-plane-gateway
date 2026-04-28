# ─────────────────────────────────────────────────────────────────────────────
# AI Control Plane Gateway — Production Dockerfile
# Multi-stage build: lean runtime image, non-root user, no dev dependencies
# ─────────────────────────────────────────────────────────────────────────────

# ── Stage 1: dependency builder ───────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

# Install build-time system deps (gcc needed by some packages)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --upgrade pip wheel

# Install runtime dependencies into a separate prefix so we can copy cleanly
COPY pyproject.toml ./
RUN pip install --no-cache-dir --prefix=/install .

# ── Stage 2: lean runtime image ───────────────────────────────────────────────
FROM python:3.12-slim AS runtime

LABEL org.opencontainers.image.title="AI Control Plane Gateway"
LABEL org.opencontainers.image.description="OpenAI-compatible LLM gateway with PHI redaction, cost optimization, and full governance"
LABEL org.opencontainers.image.version="0.2.0"
LABEL org.opencontainers.image.source="https://github.com/your-org/ai-control-plane-gateway"

# Security: non-root user
RUN groupadd -r gateway && \
    useradd -r -g gateway -d /app -s /sbin/nologin -c "gateway service account" gateway

WORKDIR /app

# Copy installed packages from builder stage
COPY --from=builder /install /usr/local

# Copy application source and default configs
COPY src/ src/
COPY configs/ configs/

# Runtime data directories (audit logs, cache)
RUN mkdir -p /data/audit_logs /data/cache && \
    chown -R gateway:gateway /app /data

# Hardened Python runtime env
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONFAULTHANDLER=1 \
    PYTHONHASHSEED=random \
    GATEWAY_CONFIG=configs/config.yaml \
    GATEWAY_ENV=production

USER gateway

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health').read()" || exit 1

CMD ["python", "-m", "src.main"]
