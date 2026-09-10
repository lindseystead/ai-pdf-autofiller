# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Fixed

- Deterministic enrichment now assigns `date` / `boolean` expected types from
  field semantics (e.g. `date_of_birth`, `start_date`, checkbox/consent), so
  common US/EU date strings normalize to `YYYY-MM-DD` on the default path
  without AI — matching the intended coerce behavior
- Doc accuracy: provider-key wording, `FORM_ALIASES_DIR` fallback, unwritable
  reasons, choice-field rules, test count, health version example

## [0.6.2]

### Added

- `FillReport.skipped_unwritable_fields` (+ `X-PDF-Fields-Skipped-Unwritable`) for missing widgets, `/Sig`, and unresolved checkbox/radio states — no silent drops
- Corpus fixture `vendor_opaque_sample.pdf`: opaque widget names from an anonymized inspect dump (blank synthetic page); recipe `recipes/vendor-opaque.md`
- Corpus now **6 cases / 35** expected field writes

### Changed

- Removed planning `docs/ROADMAP.md`; docs indexes and site footer point at evidence-based docs only
- Recipes README no longer labels the W-9-shaped fixture as “IRS Form W-9”

## [0.6.1]

### Added

- OpenAPI error catalog (`ERROR_CATALOG` + shared `ApiErrorEnvelope`) on `/fill`, `/preview`, `/inspect`
- Importable n8n workflow: `docs/integrations/n8n-fill-workflow.json`
- HTTP client `inspect()` / `preview()` + JSON `Accept` on `fill()`
- `docs/RELEASE.md` release runbook; `make sync-requirements` pins Docker/CI deps from `poetry.lock`
- Demo transcript capture: `scripts/capture_demo_transcript.sh`
- Recipes updated with real `/inspect` field inventories for synthetic fixtures

### Changed

- `requirements.txt` / `requirements-dev.txt` are fully pinned exports (CI verifies sync)
- Integrations guide rewritten around inspect → preview → fill


### Added

- `AliasRegistry` (`aliases.py`) — packs load via `AliasRegistry.load()` / `get_default_registry()` instead of mutating a module global at import
- Library APIs: `inspect()`, `preview()`, `fill_detailed()` alongside `fill()`
- `POST /fill` JSON mode when `Accept: application/json` (report + `pdf_base64`)
- Health checks: `semantic_provider`, `rate_limit`
- Synthetic corpus expansion: W-9-shaped, address/contact, HR hire-date alias samples (5 cases, 30/30 fields) — still synthetic, not official forms
- `.pre-commit-config.yaml` (Ruff + mypy)
- camelCase / digit-boundary splitting in `normalize_key` for AcroForm names like `txtNameLine1`

### Changed

- HTTP layer split into `pdf_autofiller.api.*`; `api_service` remains the ASGI entrypoint
- Semantic inference failures log a warning before deterministic fallback (no silent `pass`)
- Tooling: Black removed; Ruff is the only formatter; EditorConfig line length 110
- Version bump to **0.6.0**
- `run_fill_pipeline` returns `(report, mapping, field_count, page_count)`
- `forms/README.md` points at packaged packs only (no duplicate JSON tree)

### Fixed

- Checkbox field names (`chkConsent`) strip `chk_` and map through the HR consent cluster

## [0.5.0]

### Added

- `POST /preview` — mapping decisions JSON without writing a PDF
- Optional `flatten` form flag on `/fill` (and local `fill()` / `run_fill_pipeline`)
- Choice (`/Ch`) field write path; document that `/Sig` is unsupported
- Playground **Preview Mapping** button
- Golden corpus: `samples/hr_intake_sample.pdf`, `tests/fixtures/corpus/cases.json`,
  `scripts/corpus_report.py`, `make corpus-check`
- `docs/FAQ.md`; expanded n8n/Zapier notes; Pages links to ROADMAP/FAQ/inspect/compose
- Optional `LOG_FORMAT=json` structured logging
- Security headers middleware (`X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`)
- CI `docker-smoke` job (build image, curl `/health`)
- OpenAPI documents `/fill` `200 application/pdf`
- `docs/ROADMAP.md` — phased adoption and best-practices plan
- `POST /inspect` — list AcroForm fields as JSON
- `GET /samples/sample_form.pdf` — bundled demo form for the playground
- Playground: Use sample PDF, Inspect fields, password API-key field, structured errors
- `docker-compose.yml` and sample PDF in the Docker image
- `py.typed` marker; pinned Ruff `0.16.6` with explicit lint select
- README hero images (`docs/assets/social-preview.png`, `playground-preview.png`) for discoverability
- `scripts/apply-repo-metadata.sh` to set GitHub description and topics (run locally with admin `gh`)
- Expanded `pyproject.toml` keywords for search

### Fixed

- Deterministic mapping now matches the full alias-pack synonym cluster, so
  field-name fallbacks like `txtFirstName` → `firstname` still resolve
  profile keys such as `given_name` / `birthdate` without AI
- Health API docs now document the real `alias_directory` /
  `alias_pack_count` checks instead of a non-existent `alias_packs` key
- `fill()` is a local offline helper again (HTTP is `PDFAutofillerClient`)
- Form writes set `auto_regenerate=False` (pypdf best practice)
- Auth runs before rate-limit accounting; `429` includes `Retry-After`
- Docs drift: proxy header wording, pip-audit command, timeout description
- `poetry.lock` aligned with pinned Ruff `0.16.6`

### Changed

- Version bump to **0.5.0**
- `PDF_READ_TIMEOUT_SECONDS` documented as full-pipeline budget
- `FORM_ALIASES_DIR` import-time load caveat documented
- Multi-worker rate limiting guidance (Redis/ingress) clarified in OPERATIONS
- Library `allow_fallback_mapping` default aligned to `False` (matches API)
- Makefile format uses `ruff format`; commands prefer `python3`
- PyPI publish no longer swallows failures with `continue-on-error`; README notes token requirement
- README restructured for discovery: keywords, use cases, playground screenshot, stars badge
- GitHub Pages landing (`docs/site/`) updated with Open Graph / Twitter meta tags
- Docs index and asset README updated
- Field-name fallback semantics canonicalize onto alias-pack keys when possible
- HR alias pack expanded for corpus field names (`employee_name`, `startdate`, consent)

## [0.4.3]

### Fixed

- Docker/GHCR image build no longer copies files excluded by `.dockerignore`

### Added

- `CODE_OF_CONDUCT.md` and GitHub issue templates for bug reports and feature requests
- `workflow_dispatch` on the GHCR publish workflow for manual image rebuilds
- GitHub Pages workflow `enablement` for first-time site setup

### Changed

- README restructured for open-source presentation (install, API, architecture, docs index)
- `pyproject.toml` project URLs include the GitHub Pages landing page

## [0.4.2]

### Added

- Shared `acroform_fields` module and `pipeline.run_fill_pipeline()` for end-to-end fills
- Integration tests that round-trip `samples/sample_form.pdf` through the API and pipeline
- Health endpoint dependency checks (`auth`, alias pack count)
- Chunked upload reads with early size rejection
- Proxy-aware rate limiting via `TRUST_PROXY_HEADERS`

### Changed

- `render.yaml` now enables auth by default and generates `API_AUTH_TOKEN`
- Deterministic mapping coerces values once (no double coercion)
- `FORM_ALIASES_DIR` must point at a real directory or falls back to package defaults
- Rate limiter evicts stale client buckets under high cardinality

### Security

- Deploy blueprint no longer ships with authentication disabled by default

## [0.4.1]

### Added

- Automated discovery: Codespaces, GHCR, GitHub Release wheels, GitHub Pages (see [0.4.0] for feature list)

## [0.4.0]

### Added

- **Browser playground** at `/playground` — upload PDF, paste JSON, download filled form
- **Python SDK** (`pdf_autofiller.client`) with `fill()` convenience helper and `PDFAutofillerClient`
- **Community alias packs** for W-9 and HR onboarding (`form_aliases/*.json`)
- **Recipes** for W-9, HR onboarding, and sample form (`recipes/`)
- **Integration guides** for n8n, Zapier, and LangChain (`docs/integrations/`)
- **Render deploy** blueprint (`render.yaml`)
- **PyPI publish** GitHub Actions workflow (on release)

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
