# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Security

- `_safe_header_value` stripped non-ASCII bytes but kept ASCII control characters. A crafted PDF field name containing CR/LF could break response header framing on `X-PDF-Fields-Failed` and the skip headers — a 500 on a strict ASGI server, response splitting on a permissive one. Output is now restricted to printable ASCII.
- Documented and mitigated **prompt injection via uploaded PDFs**. Page text and field names are attacker-controlled and, when the optional model path is enabled, reach a model prompt. Model output is now constrained to a strict identifier pattern, model confidence is capped below the review threshold, fallback mapping may only select caller-supplied keys, batched responses are keyed by position, and untrusted text is sanitized and fenced. See `SECURITY.md` for what this does and does not solve.
- Bounded PDF processing with a dedicated worker pool (`PDF_WORKER_THREADS`, `PDF_QUEUE_DEPTH`). A worker thread cannot be cancelled, so a timed-out job now keeps its slot until it genuinely finishes and excess requests are shed with `503 server_busy`. Previously a timed-out request returned 503 while its thread kept running unaccounted, so hostile uploads could exhaust the shared executor.
- Fixed a race where a timed-out request deleted the temporary directory while its worker was still reading and writing files. Ownership is now handed to whichever side finishes last.

### Added

- `provider_config.py`: all model settings are configurable and pinned by default — `MODEL_NAME`, `MODEL_TEMPERATURE` (now `0.0`), `MODEL_TIMEOUT_SECONDS`, `MODEL_MAX_RETRIES`, `MODEL_RETRY_BACKOFF_SECONDS`, `MODEL_SEMANTIC_BATCH_SIZE`, `MODEL_CONTEXT_CHAR_LIMIT`, `MODEL_CONFIDENCE_CEILING`, `MAPPING_REVIEW_THRESHOLD`.
- Bounded retries with exponential backoff, and an explicit per-call timeout, on every provider request.
- `PipelineTelemetry`: provider calls, retries, failures, token counts, fields inferred, and degradation reasons, surfaced via response headers and the audit log.
- New response headers: `X-PDF-Fields-Failed`, `X-PDF-Semantic-Inference`, `X-PDF-Provider-Calls`, `X-PDF-Provider-Tokens`.
- `FieldMappingDecision.confidence_source` (`deterministic` | `model`) records where a confidence came from.
- `SEMANTIC_TIMEOUT_SECONDS`: provider-backed requests get their own time budget on top of the PDF parsing budget.
- `server_busy` error code.

### Changed

- **Semantic inference is now batched.** It previously constructed a client and issued one provider call *per field*; a 25-field form cost 25 calls. It now issues one call per `MODEL_SEMANTIC_BATCH_SIZE` fields. Combined with the separate time budget, `use_semantic_inference=true` no longer reliably times out on forms with more than ~15 fields.
- **Model self-reported confidence no longer clears the review gate.** It is clamped to `MODEL_CONFIDENCE_CEILING` (0.75), below `MAPPING_REVIEW_THRESHOLD` (0.80), so model-derived mappings are flagged for review by default. Operators can raise the ceiling to restore the previous behavior.
- **`fill_pdf` verifies its writes.** `FillReport.written_fields` now lists fields confirmed present in the output document; anything the PDF library declined to persist appears in the new `failed_fields`. Verification fails closed: if the output cannot be re-read or exposes no fields, nothing is claimed as written. A required field that cannot be verified raises `UnresolvedRequiredFieldsError` **where the input document exposed enough structure for the writer to know the field is required**; when the writer's form introspection returns nothing, required-ness is unknowable at that point and those fields are reported in `failed_fields` instead. Required fields that could not be *mapped* are still rejected before any write. Previously a field was recorded as written before the write was attempted, and write failures were swallowed at debug level.
- **A degraded model path is now visible.** Inference failures were silently swallowed; they are now logged, recorded in telemetry, and reported via `X-PDF-Semantic-Inference` and the audit line, which distinguishes *requested* from *applied*.
- `map_user_data_to_fields` defaults now match the HTTP API (`strict=True`, `allow_fallback_mapping=False`). The library previously enabled the provider path by default while the API did not.
- The provider SDK is referenced directly instead of via a runtime-assembled attribute name, restoring static analysis over the provider call site.
- Dev tooling is **pinned** (`ruff`, `mypy`, `black`, `pytest`, `pytest-cov`, `pip-audit`) and the ruff rule set is declared explicitly in `pyproject.toml`. Unpinned floors plus an implicit rule set meant a linter release could turn a green build red with no code change.
- `run_fill_pipeline` returns a `PipelineResult` instead of a bare tuple.
- Setting `MODEL_PROVIDER_API_KEY` no longer implies the model path is in effect for a given request; clients should check `X-PDF-Semantic-Inference` on the response.

### Fixed

- Rendered field-name headers were unbounded. Combined with fail-closed verification, a form with many fields could push `X-PDF-Fields-Failed` past the ~8 KB most servers and proxies accept, turning a successful fill into a failed response. The lists are now capped at 1024 characters, and new `X-PDF-Fields-Failed-Count`, `X-PDF-Fields-Skipped-Review-Count`, and `X-PDF-Fields-Skipped-Empty-Count` headers carry the untruncated totals.
- An exhausted inference budget was reported as a provider failure. Hitting the deadline before any attempt fell through to `RuntimeError("Semantic inference failed: None")`, which the batch loop counted as `semantic_batch_failed` — telemetry showed a provider outage that never happened. A distinct `SemanticBudgetExhaustedError` (a `RuntimeError` subclass, so existing callers are unaffected) now records it as degradation instead.
- Provider-backed fallback mapping sent **sanitized** field names to the model but looked responses up by the **raw** name. Any name changed by NFKC normalization, control-character stripping, whitespace collapsing, or truncation silently missed, so the field was dropped and the paid call wasted. Responses are now keyed by a synthetic per-field id, which also removes the collision risk when two raw names sanitize to the same string.
- Write verification failed **open**: when the output could not be re-read or exposed no fields, every intended field was reported as written. `written_fields` therefore claimed a confirmation the service never obtained. It now fails closed and reports those fields as unverified.
- A single failing batch in `infer_semantics_batch` discarded the fields every earlier batch had already resolved. Batches are now isolated; the call only raises if every batch failed.
- A non-numeric `confidence` in a fallback-mapping response raised out of the per-field loop and discarded every field already resolved from that call. Malformed confidences are now coerced to `0.0` per field.
- Worst-case provider wall time scaled with batch count — each batch could spend `MODEL_TIMEOUT_SECONDS * (MODEL_MAX_RETRIES + 1)` plus backoff — so a many-batch document could hold its worker slot far longer than the request budget implied. A single deadline now covers the whole batch loop and trims each call's timeout; fields resolved before the budget runs out are kept.
- Fallback mapping coerced each value twice, discarding the ambiguity flag from the first pass; it now coerces once and preserves `requires_review`.
- Removed three backward-compatibility wrappers in `api_service.py` that existed only for tests, plus the test-only rate-limiter reset helper.
- Removed `TextRegion.x` / `TextRegion.y`, which were declared but never populated.

### Documentation

- README hero images (`docs/assets/social-preview.png`, `playground-preview.png`) for discoverability
- `scripts/apply-repo-metadata.sh` to set GitHub description and topics (run locally with admin `gh`)
- Expanded `pyproject.toml` keywords for search
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
