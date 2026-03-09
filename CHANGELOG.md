# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Added

- FastAPI service wrapper with `GET /health`, `GET /version`, and `POST /fill` endpoints.
- API tests covering health/version checks and PDF fill upload behavior.
- Container runtime files (`Dockerfile`, `.dockerignore`) for deployable packaging.
- Additional regression coverage for response parsing, annotation fallback writing, and API page-context handling.
- Maintainer-facing project docs for API usage, architecture, operations, and contribution flow.
- A pull request template for consistent review hygiene.

### Changed

- Updated README and docs index to align with current API-focused scope.
- Updated dependency manifests to include API runtime packages (`fastapi`, `uvicorn`, `python-multipart`).
- Added API hardening controls: optional API key auth, upload size limit, and request ID logging.
- Split runtime and development pip dependencies into `requirements.txt` and `requirements-dev.txt`.
- Improved sample-form generation so the preferred path produces a real fillable form.
- Improved PDF writer fallback handling for annotation-backed forms and tightened temp-file cleanup in the API layer.
- Tightened repository governance with `main`-only CI triggers and a higher coverage floor.

## [0.1.0] - 2025-12-12

### Added (0.1.0)

- Initial release
- PDF reading and form field extraction
- Optional semantic inference for form fields
- Deterministic data mapping with controlled fallback mapping
- PDF form filling functionality
- Comprehensive test suite
- Documentation and examples

### Project Organization

- Organized codebase into proper directory structure
- Separated scripts, samples, and documentation
- Added development tools (Makefile, .editorconfig, .gitignore)
- Enhanced pyproject.toml with metadata and tooling config

### Structure

- `src/pdf_autofiller/` - Core application code
- `tests/` - Unit and integration tests
- `scripts/` - Utility and demo scripts
- `samples/` - Sample PDF forms for testing
- `docs/` - Documentation files
