# Architecture

## Module Boundaries

- `src/pdf_autofiller/acroform_fields.py`: shared AcroForm field extraction for reader and writer
- `src/pdf_autofiller/pdf_reader.py`: reads PDF metadata, fields, and visible text without invoking external services
- `src/pdf_autofiller/provider_config.py`: all model-provider configuration and the `ProviderUsage` telemetry accumulator
- `src/pdf_autofiller/untrusted_text.py`: sanitizing, fencing, and output constraints for attacker-controlled document text
- `src/pdf_autofiller/field_semantics.py`: wraps provider calls, batches them, and normalizes model responses
- `src/pdf_autofiller/mapping.py`: performs deterministic matching first and uses fallback mapping only for unresolved high-value fields
- `src/pdf_autofiller/pdf_writer.py`: writes validated field values, verifies them against the output, and enforces required-field completion
- `src/pdf_autofiller/pipeline.py`: orchestrates extract → enrich → map → write for API, SDK, and tests
- `src/pdf_autofiller/api_service.py`: owns the HTTP contract, auth, request validation, worker-pool bounds, and the temporary file lifecycle
- `src/pdf_autofiller/models.py`: defines the shared data contracts between each stage

## Data Flow

1. The API accepts a PDF upload and `user_data`.
2. The PDF reader extracts fields, metadata, and visible text.
3. The semantics stage infers field meaning from field metadata and optional page-level text context. When enabled, it issues **one batched provider call per `MODEL_SEMANTIC_BATCH_SIZE` fields**, not one per field.
4. The mapping stage resolves user data keys to form fields using deterministic rules first.
5. The writer applies approved values, re-reads the output to confirm each value landed, and rejects outputs with unresolved required fields.
6. The API returns the PDF along with headers describing what was written, what was skipped, and what the model path actually did.

## Design Principles

- Deterministic-first behavior keeps the default path auditable and repeatable. The default path makes **no network calls at all**.
- Optional provider-backed features are additive, not mandatory — and when they do not apply, that is reported rather than hidden.
- Errors return explicit machine-readable codes so clients can branch on behavior.
- Required fields are enforced before output leaves the service.
- Nothing is reported as done because it was attempted. Writes are verified; model activity is measured.

## Trust Boundaries

Two inputs are untrusted and are treated differently from each other:

- **The uploaded PDF** is fully attacker-controlled — its bytes, its field names,
  and its page text. Parsing is bounded (size, page count, text volume, wall
  clock, worker slots). Its *text* is additionally a prompt-injection vector once
  the model path is enabled; see `SECURITY.md` for the controls and their limits.
- **`user_data`** belongs to the caller. It is never sent to a model provider —
  only its key names and value *type* names are.

## Confidence Provenance

`FieldMappingDecision.confidence_source` records where a confidence came from:

- `deterministic` — assigned by the matching rule that fired (exact, alias,
  ambiguous coercion). These are properties of the rule, so they may clear the
  review gate.
- `model` — self-reported by a language model. Not calibrated, so it is clamped
  to `MODEL_CONFIDENCE_CEILING`, which defaults below `MAPPING_REVIEW_THRESHOLD`.
  With defaults, a model-derived mapping is always flagged for review rather than
  written unattended.

## Failure Posture

The model path is optional, so every failure in it degrades to deterministic
behavior rather than failing the request. Degradation is always **recorded**, in
three places: the `PipelineTelemetry` returned by the pipeline, the
`X-PDF-Semantic-Inference` response header, and the `audit action=fill` log line.
A silent fallback that looks identical to success is treated as a defect.

## Extension Points

- Add semantic aliases in `FIELD_ALIASES` when new field conventions are common and stable.
- Extend `coerce_value` when additional normalized data types become necessary.
- Swap providers by replacing the SDK behind `provider_sdk` in `field_semantics.py`; that module is the only place the concrete provider is named.
- Add new API endpoints in `api_service.py` only when the response contract is clear and test coverage is updated.
- Keep experimental or operator-only flows in `scripts/` so the service contract remains focused.
