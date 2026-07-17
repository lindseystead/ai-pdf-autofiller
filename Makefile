# Makefile for PDF Autofiller

.PHONY: help install install-runtime test test-cov smoke-check verify-claims lint format clean run-sample create-sample run-api playground demo-output install-release

help:
	@echo "Available commands:"
	@echo "  make install         - Install development dependencies"
	@echo "  make install-runtime - Install runtime dependencies only"
	@echo "  make test            - Run tests"
	@echo "  make test-cov        - Run tests with coverage reporting"
	@echo "  make smoke-check     - Run the local smoke-check script"
	@echo "  make verify-claims   - Verify README/API claims against the package"
	@echo "  make lint            - Run linters"
	@echo "  make format          - Format code"
	@echo "  make clean           - Clean build artifacts"
	@echo "  make run-sample      - Run demo with sample form"
	@echo "  make create-sample   - Regenerate the sample PDF form"
	@echo "  make run-api         - Run FastAPI service"
	@echo "  make playground      - Open playground URL hint"
	@echo "  make install-release - Install SDK from latest GitHub Release wheel"

install:
	poetry install || pip install -r requirements-dev.txt

install-runtime:
	pip install -r requirements.txt

test:
	PYTHONPATH=src pytest tests/ -v

test-cov:
	PYTHONPATH=src pytest tests/ --cov=src --cov-report=html --cov-report=term --cov-fail-under=85

smoke-check:
	PYTHONPATH=src python -m scripts.smoke_check

verify-claims:
	PYTHONPATH=src python -m scripts.verify_claims

lint:
	ruff check src/ tests/ scripts/
	mypy src/

format:
	black src/ tests/ scripts/
	ruff check --fix src/ tests/ scripts/

clean:
	rm -rf build/ dist/ *.egg-info .pytest_cache .mypy_cache .ruff_cache
	find . -type d -name __pycache__ -exec rm -r {} +
	find . -type f -name "*.pyc" -delete

run-sample:
	PYTHONPATH=src python -m scripts.demo_workflow samples/sample_form.pdf

create-sample:
	python scripts/create_sample_form.py

run-api:
	PYTHONPATH=src python -m uvicorn pdf_autofiller.api_service:app --host 0.0.0.0 --port 8000

playground:
	@echo "Playground: http://localhost:8000/playground (run 'make run-api' first)"

install-release:
	bash scripts/install-from-release.sh
