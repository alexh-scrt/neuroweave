.PHONY: install test test-unit test-e2e test-integration test-cov lint format run demo docs docs-serve build publish clean

# ---------------------------------------------------------------------------
# Installation
# ---------------------------------------------------------------------------

install:
	pip install -e ".[dev]"

install-docs:
	pip install -e ".[docs]"

# ---------------------------------------------------------------------------
# Testing
# ---------------------------------------------------------------------------

test:
	pytest

test-unit:
	pytest tests/test_extraction.py tests/test_graph.py tests/test_query.py \
	       tests/test_nl_query.py tests/test_events.py tests/test_api.py

test-e2e:
	pytest tests/test_e2e.py tests/test_live_updates.py

test-integration:
	pytest tests/test_integration.py

test-cov:
	pytest --cov=neuroweave --cov-report=term-missing --cov-report=html

# ---------------------------------------------------------------------------
# Code quality
# ---------------------------------------------------------------------------

lint:
	ruff check src/ tests/

format:
	ruff format src/ tests/
	ruff check --fix src/ tests/

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

run:
	python -m neuroweave.main

demo:
	python examples/demo_agent.py

demo-interactive:
	python examples/demo_agent.py --interactive

# ---------------------------------------------------------------------------
# Documentation
# ---------------------------------------------------------------------------

docs:
	mkdocs build --strict

docs-serve:
	mkdocs serve --dev-addr 127.0.0.1:8000

# ---------------------------------------------------------------------------
# Publishing
# ---------------------------------------------------------------------------

build:
	python -m build

publish: clean build
	python -m twine upload dist/*

publish-test: clean build
	python -m twine upload --repository testpypi dist/*

# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

clean:
	rm -rf .pytest_cache .coverage htmlcov dist build *.egg-info site/
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
