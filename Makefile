.PHONY: install test test-unit test-e2e test-cov lint format run clean

install:
	pip install -e ".[dev]"

test:
	pytest

test-unit:
	pytest tests/test_extraction.py tests/test_graph.py

test-e2e:
	pytest tests/test_e2e.py

test-cov:
	pytest --cov=neuroweave --cov-report=term-missing

lint:
	ruff check src/ tests/

format:
	ruff format src/ tests/
	ruff check --fix src/ tests/

run:
	python -m neuroweave.main

clean:
	rm -rf .pytest_cache .coverage htmlcov dist *.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
