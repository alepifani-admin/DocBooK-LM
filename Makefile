PY := .venv/bin/python
PIP := .venv/bin/pip

.PHONY: setup api check test lint fmt stop clean

setup:
	uv venv --python 3.12 .venv
	uv pip install --python .venv/bin/python -e ".[dev]"
	@cp -n .env.example .env 2>/dev/null || true

api:
	$(PY) -m uvicorn docbooklm.api:app --host 127.0.0.1 --port 8078

check: lint test

test:
	$(PY) -m pytest

lint:
	.venv/bin/ruff check src tests
	.venv/bin/mypy

fmt:
	.venv/bin/ruff check --fix src tests
	.venv/bin/ruff format src tests

stop:
	@-pkill -f "uvicorn docbooklm.api:app" 2>/dev/null || true
	@echo "DocBooK LM fermato"

clean:
	rm -rf .venv .pytest_cache .ruff_cache .mypy_cache data/docbook.db
