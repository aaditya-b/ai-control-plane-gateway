.PHONY: install dev run test lint format typecheck docker clean

install:
	pip install -e .

dev:
	pip install -e ".[dev]"

run:
	python -m src.main configs/config.yaml

test:
	python -m pytest tests/ -v

lint:
	ruff check src/ tests/

format:
	ruff format src/ tests/

typecheck:
	mypy src/

docker:
	docker build -t ai-control-plane-gateway:latest .

docker-run:
	docker run -p 8080:8080 --env-file .env ai-control-plane-gateway:latest

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	rm -rf .mypy_cache .pytest_cache .ruff_cache dist build
