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
PYTHONPATH=src pytest tests/ -v
```

Run the smoke-check script:

```bash
PYTHONPATH=src python -m scripts.smoke_check
```

## Test Scope

Pytest coverage currently includes:

- Mapping logic (`tests/test_mapping.py`)
- AcroForm field extraction (`tests/test_acroform_fields.py`)
- PDF reader extraction flow (`tests/test_pdf_reader.py`)
- PDF writer behavior and required-field handling (`tests/test_pdf_writer.py`)
- Semantic client behavior: batching, retries, timeouts, token accounting, and rejection of unsafe model output (`tests/test_field_semantics.py`)
- Untrusted-text sanitizing and semantic-label constraints (`tests/test_untrusted_text.py`)
- Pipeline enrichment, batching, and degradation reporting (`tests/test_pipeline.py`)
- FastAPI endpoint behavior, worker-pool bounds, and time budgets (`tests/test_api_service.py`)
- End-to-end pipeline and API round-trips (`tests/test_integration.py`)

The smoke-check script (`scripts/smoke_check.py`) covers imports, model construction, mapping behavior, and the local semantic client availability path.

## Real PDF Workflow Test

Run the demo workflow against a real form:

```bash
PYTHONPATH=src python -m scripts.demo_workflow path/to/form.pdf
```

With explicit user data:

```bash
PYTHONPATH=src python -m scripts.demo_workflow path/to/form.pdf '{"firstname":"John","lastname":"Doe","dob":"1990-05-15"}'
```

## API Smoke Test

Run API locally:

```bash
make run-api
```

In another terminal:

```bash
curl -s http://localhost:8000/health
```

## Testing Without Provider Credentials

Deterministic paths can run without `MODEL_PROVIDER_API_KEY`. Semantic inference and fallback mapping require valid provider credentials.

The entire test suite runs without credentials and never contacts a provider:
provider behavior is exercised through injected fake clients. If a test ever
needs real credentials to pass, that is a bug in the test.

Requesting inference without credentials is a supported, *visible* state — the
fill succeeds deterministically and reports `X-PDF-Semantic-Inference: degraded`.

```bash
PYTHONPATH=src python -m scripts.demo_workflow samples/sample_form.pdf '{"firstname":"John","lastname":"Doe"}'
```

## Quality Commands

From repository root:

```bash
make test
make lint
make format
```

Direct commands:

```bash
ruff check src/ tests/ scripts/
mypy src/
pip-audit -r requirements.txt
PYTHONPATH=src pytest tests/ -v --cov=src --cov-report=term --cov-fail-under=85
```

## CI Validation

GitHub Actions workflow (`.github/workflows/test.yml`) runs:

- `ruff` lint checks
- `mypy` type checks
- `pip-audit` dependency audit
- `pytest` with coverage threshold
- `poetry check --lock` (separate job) to keep `poetry.lock` in step with `pyproject.toml`

on Python 3.11 and 3.12.

Dev tooling is pinned to exact versions in `requirements-dev.txt` and mirrored in
`[tool.poetry.group.dev.dependencies]`, and the ruff rule set is declared
explicitly in `pyproject.toml`. Both matter: with floored versions and an
implicit rule set, a linter release could turn a green build red without any
code change. Upgrade the pins deliberately, in a commit that also fixes whatever
the new version reports.

## Troubleshooting

- `No module named pypdf`: install dependencies with `pip install -r requirements-dev.txt`.
- `Semantic client unavailable`: set `MODEL_PROVIDER_API_KEY` or run deterministic paths only.
- `pip-audit` connection errors: the audit command queries remote advisory sources and requires outbound network access.
- `PDF file not found`: verify input path is correct.
- Import errors: ensure you are in the expected environment.
