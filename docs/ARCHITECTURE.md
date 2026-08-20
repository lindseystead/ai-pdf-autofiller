# Architecture

## Module Boundaries

- `src/pdf_autofiller/acroform_fields.py`: shared AcroForm field extraction for reader and writer
- `src/pdf_autofiller/pdf_reader.py`: reads PDF metadata, fields, and visible text without invoking external services
- `src/pdf_autofiller/field_semantics.py`: wraps provider calls and normalizes model responses
- `src/pdf_autofiller/mapping.py`: performs deterministic matching first and uses fallback mapping only for unresolved high-value fields
- `src/pdf_autofiller/pdf_writer.py`: writes validated field values and enforces required-field completion
- `src/pdf_autofiller/pipeline.py`: orchestrates extract → enrich → map → write for API, SDK, and tests
- `src/pdf_autofiller/api_service.py`: assembles the app and defines the routes — a readable list of what the service exposes
- `src/pdf_autofiller/http_support.py`: the plumbing routes rely on — error contract, auth, rate limiting, payload bounds, upload staging
- `src/pdf_autofiller/cli.py`: the command line, running the same pipeline in-process with no server
- `src/pdf_autofiller/client.py`: HTTP client SDK for the service
- `src/pdf_autofiller/execution.py`: runs untrusted PDF parsing in a killable child process
- `src/pdf_autofiller/store.py`: JSON-file storage for templates and profiles
- `src/pdf_autofiller/settings.py`: one validated configuration object, built from the environment at startup
- `src/pdf_autofiller/errors.py`: typed domain errors, each carrying the code and status the HTTP layer returns
- `src/pdf_autofiller/semantics_cache.py`: bounded in-process cache of inferred semantics, keyed by form fingerprint
- `src/pdf_autofiller/models.py`: defines the shared data contracts between each stage

## Data Flow

Two entry points share the same four stages. `inspect` stops after mapping and
reports what a fill *would* do; `fill` runs all four and produces the document.

```
inspect  ──┐
fill     ──┴──▶  read ──▶ enrich ──▶ map ──▶ write
```

1. The API or CLI accepts a PDF and `user_data`.
2. The PDF reader extracts fields, metadata, and visible text.
3. The semantics stage infers field meaning from field metadata and optional page-level text context.
4. The mapping stage resolves user data keys to form fields using deterministic rules first.
5. The writer applies approved values and rejects outputs with unresolved required fields.

Mapping is a global assignment over every (field, key) pair rather than greedy
first-match, so the result does not depend on the order of keys in `user_data`.

## Design Principles

- Deterministic-first behavior keeps the default path auditable and repeatable.
- Optional provider-backed features are additive, not mandatory.
- Errors return explicit machine-readable codes so clients can branch on behavior.
- Required fields are enforced before output leaves the service.

## Extension Points

- Add semantic aliases to `BUILTIN_FIELD_ALIASES`, or ship a JSON pack in `form_aliases/`. Packs are merged into the built-ins per key — they extend an alias list, never replace it. `tests/test_alias_packs.py` validates every shipped pack: a pack may not weaken a built-in, claim one variant for two semantics within itself, or re-declare a concept the built-ins already own.
- Add a new CLI command as one function in `cli.py` plus a subparser; commands call the pipeline directly and hold no logic of their own.
- Add a new failure mode as a class in `errors.py`; it surfaces over HTTP with no change to the route layer.
- Extend `coerce_value` when additional normalized data types become necessary.
- Add new API endpoints in `api_service.py` only when the response contract is clear and test coverage is updated.
- Keep experimental or operator-only flows in `scripts/` so the service contract remains focused.
