# PDF Autofiller

Backend service for filling AcroForm PDFs from structured user data.

The project favors deterministic behavior first: it normalizes keys, applies stable aliases, coerces values, and only uses optional semantic inference or controlled fallback mapping when explicitly enabled. The result is a small, testable pipeline that is easier to audit than heuristic-only form filling.

## What It Does

- Reads PDF metadata, form fields, and visible page text
- Infers semantic meaning for fields when optional semantic inference is enabled
- Maps user data to fields using deterministic rules first
- Rejects outputs with unresolved required fields
- Returns a new filled PDF through a small FastAPI service

## Quick Start

Install development dependencies:

```bash
poetry install
```

or

```bash
pip install -r requirements-dev.txt
```

Run the API locally:

```bash
make run-api
```

Run the local smoke check:

```bash
PYTHONPATH=src python -m scripts.smoke_check
```

Run the demo workflow against the bundled sample:

```bash
PYTHONPATH=src python -m scripts.demo_workflow samples/sample_form.pdf
```

## API Example

```bash
curl -s -X POST http://localhost:8000/fill \
  -F "pdf_file=@samples/sample_form.pdf;type=application/pdf" \
  -F 'user_data={"firstname":"Jane","lastname":"Doe","dob":"1990-01-01"}' \
  -F "strict=true" \
  -o filled.pdf
```

## Configuration

- `MODEL_PROVIDER_API_KEY`: enables semantic inference and fallback mapping
- `API_AUTH_ENABLED`: API key validation on `POST /fill` (default `true`; set `false` for trusted/local use)
- `API_AUTH_TOKEN`: expected token value when auth is enabled
- `API_KEY_HEADER`: header name used for the incoming token
- `MAX_UPLOAD_BYTES`: maximum accepted PDF size in bytes
- `MAX_PDF_PAGES`: maximum accepted page count (default `200`)
- `PDF_READ_TIMEOUT_SECONDS`: budget for PDF parsing/extraction (default `20`)
- `RATE_LIMIT_PER_MINUTE`: per-client `POST /fill` budget; `0` disables (default `60`)
- `LOG_LEVEL`: process log level for the API service

## Architecture

Core code lives in `src/pdf_autofiller/` and is intentionally split by responsibility:

- `pdf_reader.py`: extraction only
- `field_semantics.py`: provider client wrapper and response normalization
- `mapping.py`: deterministic matching and controlled fallback mapping
- `pdf_writer.py`: output writing and required-field enforcement
- `api_service.py`: HTTP boundary, auth, request validation, and temp-file lifecycle

The detailed system breakdown is in `docs/ARCHITECTURE.md`.

## Quality

- `ruff`, `mypy`, `pip-audit`, and `pytest` are enforced in CI
- Coverage floor is `85%`
- API error responses use stable machine-readable error codes
- Smoke-check and demo scripts are kept separate from the test suite

## Scope

- The current pipeline targets fillable AcroForm PDFs
- OCR and scanned-document workflows are intentionally out of scope
- Frontend, persistence, and deployment infrastructure are not part of this repository
- If optional provider-backed features are enabled, field metadata and nearby page text may be sent to an external service

## Documentation

- `docs/API.md`: endpoint contracts and example requests
- `docs/ARCHITECTURE.md`: module boundaries and data flow
- `docs/OPERATIONS.md`: runtime configuration and deployment assumptions
- `docs/TESTING.md`: local validation workflow
- `docs/PURPOSE.md`: problem statement and intended usage
- `CONTRIBUTING.md`: contributor expectations
- `SECURITY.md`: vulnerability reporting and data-handling notes

## License

MIT. See `LICENSE`.
