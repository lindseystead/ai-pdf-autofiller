# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Fixed

- **Community alias packs no longer delete the built-in aliases they extend.**
  `FIELD_ALIASES.update()` replaced a semantic's alias list wholesale, so a pack
  adding one variant for `first_name` removed `firstname`, `given_name`,
  `forename`, and `fname`. Alias maps are now merged per key.
- **A hostile PDF can no longer permanently consume a worker.** PDF parsing ran
  under `asyncio.wait_for` around a thread, which cancels the wait but cannot
  interrupt the work; the endpoint returned 503 while the thread ran on forever.
  Parsing now runs in a killable child process, which also contains parser
  memory blowups and hard crashes.
- **`user_data` is now bounded.** The upload was chunk-limited while the JSON
  form field beside it was an unbounded string handed to `json.loads`. Size,
  key count, and nesting depth are all enforced.
- **Nested user data now maps.** Only top-level keys were ever inspected, so a
  nested profile silently mapped nothing and reported the container key as
  unused. Data is flattened to dotted paths and matched on both path and leaf.
- **Mapping no longer depends on `user_data` key order.** Greedy first-match
  meant the same data submitted twice could fill a form differently. Every
  (field, key) pair is scored and assigned best-first.
- **Choice and signature fields are validated.** `/Ch` values are checked
  against the field's declared `/Opt` options and `/Sig` fields are never
  written, since text in a signature field cannot make a valid signature and
  destroys an existing one. Both now report under `skipped_invalid_fields`.
- Added the `py.typed` marker. The package advertised `Typing :: Typed` without
  it, so type checkers treated the whole SDK as untyped downstream.
- The writer now issues one document-wide field update instead of re-sending
  every value once per page, and passes `auto_regenerate=False` so the
  appearance streams it generates are kept rather than handed back to the viewer
  to rebuild (which also prompted a spurious "save changes" dialog).

### Added

- **`pdf-autofiller` CLI** with `inspect`, `fill`, `validate`, `batch`,
  `profile`, and `template` commands, all running in-process — filling one PDF
  no longer requires starting a server.
- **`POST /v1/inspect`** reports a form's fields and previews exactly what a
  fill would do, without writing anything. Field discovery no longer means
  guessing key names and reading a 422.
- **Templates and profiles.** A template remembers the overrides that made a
  form come out right, keyed by a fingerprint of its field structure; a profile
  is a named, reusable set of data. Both are available over HTTP and the CLI.
- **Batch filling** via `pdf-autofiller batch`. A failing row is recorded and
  the rest of the batch continues.
- **`flatten` option** that stamps values into page content and removes the
  interactive form, so a completed document cannot be edited downstream.
  (pypdf's own `flatten` leaves the AcroForm and widgets in place; this removes
  them.)
- **Typed errors** for encrypted, XFA, malformed, and field-less PDFs. All four
  previously surfaced as "zero fields found", pointing users at the wrong cause.
- **Explicit `overrides`** — a `{field_name: value}` map that wins outright, for
  the cases mapping will never get right.
- **JSON response mode** on fill (`response_format=json` or an
  `Accept: application/json` header) returning the full `FillReport` and mapping
  decisions alongside the base64-encoded document. The header-based report is
  ASCII-stripped and length-capped.
- **Opt-in CORS** via `CORS_ALLOW_ORIGINS`. There is no wildcard default.
- `SDK`: `inspect()` and `fill_with_report()`, plus `flatten`, `overrides`,
  `template`, and `profile` arguments on `fill()`.
- Adversarial-PDF and property-based test suites (202 tests total).
- README hero images (`docs/assets/social-preview.png`, `playground-preview.png`) for discoverability
- `scripts/apply-repo-metadata.sh` to set GitHub description and topics (run locally with admin `gh`)
- Expanded `pyproject.toml` keywords for search

### Changed

- **Semantic inference is now a single batched call per form.** Inference ran
  once per field, serially, inside one request budget — a 60-field form meant 60
  round trips, which timed out and cost 60x what it should. Results are also
  cached against the form fingerprint, so the same form filled twice infers once.
- Inference requests a strict JSON schema where the provider supports it,
  falling back to JSON mode automatically, with local validation either way.
  Field names the form does not contain are discarded rather than mapped.
- The model provider is configurable (`MODEL_PROVIDER_MODEL`) and has a timeout
  and bounded retries; the model was previously hardcoded at two call sites with
  no timeout inside a hard request deadline.
- Configuration is a single validated `Settings` object built from the
  environment, replacing module globals read at import time. A malformed numeric
  variable now raises a readable configuration error instead of a traceback
  during import.
- Routes are served under `/v1`. Unversioned paths remain as aliases.
- `/fill` accepts a request with no `user_data` when a profile or template
  supplies the values, but rejects one where no data source is present at all —
  that would return an unchanged document that looks like a successful fill.
- `FormField` now carries `options` (a choice field's `/Opt` values or a
  button's export states), so callers can see what a constrained field accepts.
- HTTP plumbing (auth, rate limiting, payload bounds, upload staging, the error
  contract) moved to `http_support.py`, leaving `api_service.py` as a readable
  list of what the service exposes.
- README restructured for discovery: keywords, use cases, playground screenshot, stars badge
- GitHub Pages landing (`docs/site/`) updated with Open Graph / Twitter meta tags
- Docs index and asset README updated

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
