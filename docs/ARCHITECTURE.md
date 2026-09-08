# Architecture

## Module Boundaries

- `aliases.py`: `AliasRegistry` — built-in synonym clusters + JSON packs under `form_aliases/`
- `acroform_fields.py`: shared AcroForm field extraction for reader and writer
- `pdf_reader.py`: reads PDF metadata, fields, and visible text without external services
- `field_semantics.py`: optional provider calls; never required on the default path
- `mapping.py`: deterministic matching (normalize → aliases → coerce); optional provider fallback
- `pdf_writer.py`: writes validated values; enforces required-field completion
- `pipeline.py`: extract → enrich → map → write; exports `fill`, `fill_detailed`, `inspect`, `preview`
- `client.py`: optional HTTP client for a remote API
- `api/`: FastAPI app split into `config`, `security`, `middleware`, `errors`, `uploads`, `schemas`, `routes`
- `api_service.py`: thin public ASGI / console-script entry (`pdf_autofiller.api_service:app`)
- `playground.py` + `static/`: browser playground UI
- `models.py`: Pydantic contracts between stages

## HTTP endpoints

| Method | Path | Notes |
|--------|------|-------|
| `GET` | `/` | Redirect to `/playground` |
| `GET` | `/playground` | Browser UI |
| `GET` | `/health` | Auth / alias / semantic-provider readiness |
| `GET` | `/version` | Service identity and version |
| `GET` | `/samples/sample_form.pdf` | Bundled demo form (unauthenticated) |
| `POST` | `/inspect` | AcroForm field inventory JSON |
| `POST` | `/preview` | Mapping decisions without writing a PDF |
| `POST` | `/fill` | PDF bytes by default; JSON report + `pdf_base64` when `Accept: application/json` |

## Data Flow

1. Accept PDF + `user_data` (API) or local paths (library).
2. Reader extracts fields, metadata, and visible text.
3. Enrichment is deterministic by default (field-name → semantic via `AliasRegistry`). Optional provider inference logs failures and falls back — never silent.
4. Mapping resolves user keys via normalization and alias clusters first.
5. Writer applies approved values and rejects unresolved required fields. Mapped values that cannot be written (missing widget, `/Sig`, unresolved button state) are listed on `FillReport.skipped_unwritable_fields` — never silent.

## Design Principles

- Deterministic-first: default path is auditable without an API key.
- Optional provider features are additive and observable (`semantic_provider` health check).
- Errors use explicit machine-readable codes.
- Required fields are enforced before output leaves the service.
- Alias packs are loaded through `AliasRegistry` (restart or `set_default_registry` to reload).

## Extension Points

- Add JSON packs under `src/pdf_autofiller/form_aliases/` (not top-level `forms/`).
- Prove packs with a synthetic case in `tests/fixtures/corpus/cases.json`.
- Extend `coerce_value` when new normalized data types are needed.
- Keep operator-only flows in `scripts/` so the public contract stays focused.

## What this is not

- Not an OCR / scanned-PDF filler (AcroForm widgets only).
- Not a claim of official IRS/vendor form certification — corpus PDFs are synthetic stand-ins unless a redacted real fixture is added.
