# Testing Guide

This guide covers local test execution and quality checks for the PDF autofiller service.

## Quick Start

Create and activate a virtual environment if needed:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements-dev.txt
```

Run the test suite:

```bash
PYTHONPATH=src python3 -m pytest tests/ -v
```

Run the smoke-check script:

```bash
PYTHONPATH=src python3 -m scripts.smoke_check
```

Golden corpus hit-rate gate:

```bash
make corpus-check
```

## Test Scope

Pytest coverage currently includes:

- Mapping logic (`tests/test_mapping.py`)
- AcroForm field extraction (`tests/test_acroform_fields.py`)
- PDF reader extraction flow (`tests/test_pdf_reader.py`)
- PDF writer behavior and required-field handling (`tests/test_pdf_writer.py`)
- Real-world form structures — radio groups, hierarchical names, nested JSON,
  `/MaxLen`, partial fills, flatten output (`tests/test_form_structures.py`,
  fixtures built by `tests/form_factory.py`)
- CLI commands (`tests/test_cli.py`)
- Semantic client wrapper behavior and parsing (`tests/test_field_semantics.py`)
- Field utilities (`tests/test_field_utils.py`)
- FastAPI endpoint behavior (`tests/test_api_service.py`)
- HTTP client SDK (`tests/test_client.py`)
- Library API helpers (`tests/test_library_api.py`)
- OpenAPI error catalog (`tests/test_error_catalog.py`)
- PDF job timeout isolation (`tests/test_jobs.py`)
- Playground routes and UI markers (`tests/test_playground.py`)
- Golden corpus fixtures (`tests/test_corpus.py`)
- End-to-end pipeline and API round-trips (`tests/test_integration.py`)

The smoke-check script (`scripts/smoke_check.py`) covers imports, model construction, mapping behavior, and the local semantic client availability path.

## Real PDF Workflow Test

Inspect a real form, preview the mapping, then fill it with the CLI:

```bash
pdf-autofiller inspect path/to/form.pdf
pdf-autofiller preview path/to/form.pdf --data '{"firstname":"John","lastname":"Doe","dob":"1990-05-15"}'
pdf-autofiller fill path/to/form.pdf --data '{"firstname":"John","lastname":"Doe","dob":"1990-05-15"}' -o filled.pdf
```

## API Smoke Test

Run API locally:

```bash
API_AUTH_ENABLED=false make run-api
```

In another terminal:

```bash
curl -s http://localhost:8000/health
```

## Testing Without Provider Credentials

Deterministic paths, including every command above, run without `MODEL_PROVIDER_API_KEY`.
Semantic inference (`--ai`) and fallback mapping (`--no-strict`) require valid provider credentials.

## Quality Commands

From repository root:

```bash
make test
make test-cov
make lint
make format
make smoke-check
make corpus-check
```

Direct commands:

```bash
ruff check src/ tests/ scripts/
ruff format --check src/ tests/ scripts/
mypy src/
pip-audit -r requirements.txt
PYTHONPATH=src python3 -m pytest tests/ -v --cov=src --cov-report=term --cov-fail-under=85
```

## CI Validation

GitHub Actions workflow (`.github/workflows/test.yml`) runs these jobs:

- `test` — `ruff check`, `ruff format --check`, `mypy`, `pip-audit`, and `pytest` with coverage threshold (Python 3.11 and 3.12)
- `docker-smoke` — build the Docker image and curl `/health`
- `lockfile` — verify `poetry.lock` is in sync with `pyproject.toml` and that `requirements*.txt` match the lock

## Troubleshooting

- `No module named pypdf`: install dependencies with `pip install -r requirements-dev.txt`.
- `Semantic client unavailable`: set `MODEL_PROVIDER_API_KEY` or run deterministic paths only.
- `pip-audit` connection errors: the audit command queries remote advisory sources and requires outbound network access.
- `PDF file not found`: verify input path is correct.
- Import errors: ensure you are in the expected environment.
