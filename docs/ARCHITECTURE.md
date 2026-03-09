# Architecture

## Module Boundaries

- `src/pdf_autofiller/pdf_reader.py`: reads PDF metadata, fields, and visible text without invoking external services
- `src/pdf_autofiller/field_semantics.py`: wraps provider calls and normalizes model responses
- `src/pdf_autofiller/mapping.py`: performs deterministic matching first and uses fallback mapping only for unresolved high-value fields
- `src/pdf_autofiller/pdf_writer.py`: writes validated field values and enforces required-field completion
- `src/pdf_autofiller/api_service.py`: owns the HTTP contract, auth, request validation, and temporary file lifecycle
- `src/pdf_autofiller/models.py`: defines the shared data contracts between each stage

## Data Flow

1. The API accepts a PDF upload and `user_data`.
2. The PDF reader extracts fields, metadata, and visible text.
3. The semantics stage infers field meaning from field metadata and optional page-level text context.
4. The mapping stage resolves user data keys to form fields using deterministic rules first.
5. The writer applies approved values and rejects outputs with unresolved required fields.

## Design Principles

- Deterministic-first behavior keeps the default path auditable and repeatable.
- Optional provider-backed features are additive, not mandatory.
- Errors return explicit machine-readable codes so clients can branch on behavior.
- Required fields are enforced before output leaves the service.

## Extension Points

- Add semantic aliases in `FIELD_ALIASES` when new field conventions are common and stable.
- Extend `coerce_value` when additional normalized data types become necessary.
- Add new API endpoints in `api_service.py` only when the response contract is clear and test coverage is updated.
- Keep experimental or operator-only flows in `scripts/` so the service contract remains focused.
