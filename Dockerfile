FROM python:3.12-slim AS base

WORKDIR /app

# Install dependencies
COPY pyproject.toml ./
RUN pip install --no-cache-dir .

# Copy source
COPY src/ src/
COPY configs/ configs/

EXPOSE 8080

ENV GATEWAY_CONFIG=configs/config.yaml

CMD ["python", "-m", "src.main"]
