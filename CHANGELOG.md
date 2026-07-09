# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Added

- Launch kit: `docs/LAUNCH_CHECKLIST.md`, `docs/SHOW_HN.md`, awesome-selfhosted submission draft
- README demo section with SVG placeholder and GIF recording guide (`docs/assets/README.md`)

## [0.4.0]

### Added

- **Browser playground** at `/playground` — upload PDF, paste JSON, download filled form
- **Python SDK** (`pdf_autofiller.client`) with `fill()` convenience helper and `PDFAutofillerClient`
- **Community alias packs** for W-9 and HR onboarding (`form_aliases/*.json`)
- **Recipes** for W-9, HR onboarding, and sample form (`recipes/`)
- **Integration guides** for n8n, Zapier, and LangChain (`docs/integrations/`)
- **Launch playbook** with HN/Reddit/Product Hunt copy (`docs/LAUNCH.md`)
- **Comparison doc** vs DocuSign, Adobe, and DIY pypdf (`docs/COMPARISON.md`)
- **Render deploy** blueprint (`render.yaml`) and deployment guide (`docs/DEPLOY.md`)
- **PyPI publish** GitHub Actions workflow (on release)
- Demo transcript generator (`scripts/generate_demo_output.py`)

### Changed

- PyPI publish workflow now uses `PYPI_API_TOKEN` with clearer failure messaging
- PR template aligned with CI pip-audit command

## [0.3.1]

### Security

- Resolved `starlette` advisory PYSEC-2026-161 by raising the FastAPI floor to `>= 0.136` and pinning `starlette >= 1.0.1` (the patched line ships in the Docker image, `starlette 1.2.1`). Removed the corresponding `pip-audit` ignore; the runtime surface now audits clean with no exceptions. Verified by building and running the container.

## [0.3.0]

### Security

- **Breaking:** authentication on `POST /fill` now defaults to enabled (`API_AUTH_ENABLED=true`) and fails closed. Set `API_AUTH_ENABLED=false` for trusted/local use.
- Added per-client rate limiting on `POST /fill` (`RATE_LIMIT_PER_MINUTE`, default 60; `0` disables) → `rate_limited` (429).
- Added denial-of-service guards: page-count cap (`MAX_PDF_PAGES`, default 200) → `pdf_too_many_pages` (413), and a parsing/extraction time budget (`PDF_READ_TIMEOUT_SECONDS`, default 20) → `pdf_processing_timeout` (503). Extraction now runs off the event loop.
- PII minimization: provider-backed calls no longer send raw user-data values or a field's current value; only key names and value type names are shared.
- Hardened temporary-file cleanup so uploaded/generated PDFs are removed on every non-success path, including timeouts and cancellations.
- Bumped `pypdf` (>=6.12.2) and `python-multipart` (>=0.0.30) minimums to patched, CVE-fixed releases; these parse untrusted input. (Residual: `starlette` advisory PYSEC-2026-161 awaits FastAPI support for the patched 1.x line.)
- Bounded total extracted PDF text (`MAX_PDF_TEXT_CHARS`, default 2,000,000) to limit memory and provider-token exposure on hostile documents.
- Added a structured, PII-free per-fill audit log line (`audit action=fill ...`) recording request ID, feature flags, and field counts only.

### Changed

- Documented the new configuration, error codes, privacy behavior, and audit logging in `README.md`, `docs/API.md`, `docs/OPERATIONS.md`, and `SECURITY.md`.
- Expanded module docstrings to state the security/privacy rationale for each stage.

## [0.2.0]

### Added

- `FillReport` returned by `fill_pdf`, reporting written, review-skipped, and empty-skipped fields.
- `POST /fill` now exposes fill outcome via `X-PDF-Fields-Written`, `X-PDF-Fields-Skipped-Review`, and `X-PDF-Fields-Skipped-Empty` response headers, so non-required fields dropped for review are no longer silently lost.
- Checkbox/radio (`/Btn`) state resolution in the writer plus regression tests for truthy/falsy and report behavior.
- `docs/AUDIT.md`: consolidated document-automation architecture audit with a roadmap.

### Fixed

- Checkbox and radio fields are now written using valid PDF state names (e.g. `/Yes`/`/Off`). Boolean-style inputs (`true`/`yes`/`1`/`on`) previously left controls unchecked.

### Changed

- Documented the new response headers and button-fill behavior in `docs/API.md`.

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
