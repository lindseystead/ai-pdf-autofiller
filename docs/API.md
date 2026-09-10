# API Reference

## Endpoints

### `GET /`

Redirects to `/playground` (temporary redirect).

### `GET /playground`

Serves the browser playground UI for trying fills without curl.

The playground exposes checkboxes for `strict`, `allow_fallback_mapping` (AI fallback), `use_semantic_inference`, `flatten`, and `need_appearances`. Use curl (or the SDK) when you need full control over form flags and headers.

### `GET /health`

Returns service health metadata.

Example:

```bash
curl -s http://localhost:8000/health
```

Example response:

```json
{
  "status": "ok",
  "service": "pdf-autofiller",
  "version": "0.6.2",
  "checks": {
    "auth": "disabled",
    "semantic_provider": "unconfigured",
    "rate_limit": "in_process",
    "alias_directory": "/app/src/pdf_autofiller/form_aliases",
    "alias_pack_count": "2"
  }
}
```

`status` is `degraded` when auth is enabled but `API_AUTH_TOKEN` is unset (`checks.auth` = `misconfigured`). Alias pack availability is reported via `checks.alias_directory` and `checks.alias_pack_count`. `semantic_provider` is one of `available` | `unconfigured` | `sdk_missing` — it does not claim inference succeeded on a request. `rate_limit` is `in_process`, `shared_file`, or `disabled` depending on `RATE_LIMIT_PER_MINUTE` / `RATE_LIMIT_BACKEND`.

### `GET /version`

Returns service identity and version.

Example:

```bash
curl -s http://localhost:8000/version
```


### `GET /samples/sample_form.pdf`

Returns the bundled sample AcroForm used by the playground one-click demo.
This endpoint is **unauthenticated** (same as `/health`, `/version`, and `/playground`).

### `POST /inspect`

Accepts a PDF upload and returns AcroForm field metadata so clients can draft JSON.
Each field includes `name_quality` (`readable` or `opaque`). When names look
machine-generated, the response also includes `opaque_field_count`,
`opaque_fields`, and `mapping_hints` (exact widget keys, alias packs, or semantic inference).

Example:

```bash
curl -s -X POST http://localhost:8000/inspect \
  -F "pdf_file=@samples/sample_form.pdf;type=application/pdf"
```

Example response:

```json
{
  "pages": 1,
  "field_count": 5,
  "opaque_field_count": 0,
  "opaque_fields": [],
  "mapping_hints": [],
  "fields": [
    {
      "name": "txtFirstName",
      "field_type": "text",
      "required": true,
      "page_number": 1,
      "current_value": null,
      "name_quality": "readable"
    }
  ]
}
```

Authentication and rate limits match `POST /fill`.

### `POST /preview`

Runs extract → enrich → map **without writing a PDF**. Returns mapping decisions so you can debug misses before `/fill`.

Required form fields:

- `pdf_file`: the source PDF upload
- `user_data`: a JSON object encoded as form text

Optional form fields (same semantics as `/fill`):

- `strict` (default `true`) — disables AI fallback mapping only
- `allow_fallback_mapping` (default `false`)
- `use_semantic_inference` (default `false`) — one batched provider call when enabled

Example:

```bash
curl -s -X POST http://localhost:8000/preview \
  -F "pdf_file=@samples/sample_form.pdf;type=application/pdf" \
  -F 'user_data={"firstname":"Alex","lastname":"Example","dob":"1990-01-15"}' \
  -F "strict=true"
```

Example response:

```json
{
  "pages": 1,
  "field_count": 5,
  "decisions": [
    {
      "field_name": "txtFirstName",
      "semantic_meaning": "first_name",
      "selected_value": "Alex",
      "confidence": 0.95,
      "reason": "Direct match: 'firstname' matches semantic 'first_name'",
      "requires_review": false
    }
  ],
  "missing_required": [],
  "unmapped_user_keys": []
}
```

Authentication and rate limits match `POST /fill`.

### `POST /fill`

Accepts a multipart form upload.

**Default** (`Accept: application/pdf` or unspecified): response body is the filled PDF.

**JSON report mode** (`Accept: application/json`): response body is JSON including mapping decisions, written/skipped fields, and `pdf_base64` (standard base64 of the filled PDF). Use this when headers alone are not enough for automation.

Required form fields:

- `pdf_file`: the source PDF upload
- `user_data`: a JSON object encoded as form text

Optional form fields:

- `strict`: when `true`, **disables AI fallback mapping only** (default `true`). Required fields are still enforced on `/fill` regardless of this flag.
- `allow_fallback_mapping`: when `true`, allows fallback mapping for unresolved high-value fields (default `false`; also requires `strict=false`)
- `use_semantic_inference`: when `true`, enables a single batched semantic inference call before mapping (default `false`)
- `flatten`: when `true`, burns field appearances into page content and removes widget annotations (default `false`)
- `need_appearances`: when `true` (default), sets AcroForm `/NeedAppearances` so PDF viewers regenerate visible glyphs from written `/V` values. pypdf's `auto_regenerate` flag only toggles this bit — it does not embed new appearance streams. Use `flatten=true` when you need burned-in visuals without relying on the viewer.

Example (PDF):

```bash
curl -s -X POST http://localhost:8000/fill \
  -F "pdf_file=@samples/sample_form.pdf;type=application/pdf" \
  -F 'user_data={"firstname":"Alex","lastname":"Example","dob":"1990-01-15"}' \
  -F "strict=true" \
  -o filled.pdf
```

Example (JSON report):

```bash
curl -s -X POST http://localhost:8000/fill \
  -H "Accept: application/json" \
  -F "pdf_file=@samples/sample_form.pdf;type=application/pdf" \
  -F 'user_data={"firstname":"Alex","lastname":"Example","dob":"1990-01-15"}'
```

On PDF success the response body is `application/pdf`. OpenAPI documents both `application/pdf` and `application/json` for `200`.

Successful responses also include fill-outcome headers so clients can detect
fields that were dropped instead of silently losing them:

- `X-PDF-Fields-Written`: count of fields that received a value
- `X-PDF-Fields-Skipped-Review`: comma-separated field names skipped because the mapping was flagged for review
- `X-PDF-Fields-Skipped-Empty`: comma-separated field names skipped because the mapped value was empty
- `X-PDF-Fields-Skipped-Unwritable`: comma-separated entries `field (reason)` when a mapped value could not be written (`missing_widget`, `signature_field`, `unresolved_button_state`, `unresolved_choice_option`, or `write_failed`)

Checkbox and radio (`/Btn`) fields are written using their PDF state names, so
boolean-style inputs (`true`/`yes`/`1`/`on`) correctly toggle the control.

Choice (`/Ch`) fields: when `/Opt` or `/_States_` are present, the value must
match an option (case-insensitive) or it is skipped as `unresolved_choice_option`.
When no options are declared, the mapped value is written as-is.

**Signature (`/Sig`) fields are not filled** — digital signature widgets are unsupported.

## Error Contract

API errors return a JSON payload with a machine-readable code:

```json
{
  "detail": {
    "error": {
      "code": "invalid_user_data_json",
      "message": "Invalid user_data JSON",
      "details": {
        "reason": "Expecting property name enclosed in double quotes"
      }
    }
  }
}
```

Canonical catalog (also exposed in OpenAPI on `/fill`, `/preview`, `/inspect`):

| Code | HTTP | When |
|------|------|------|
| `request_validation_error` | 422 | Missing/invalid multipart fields |
| `invalid_user_data_json` | 422 | `user_data` is not valid JSON |
| `invalid_user_data_type` | 422 | `user_data` is not a JSON object |
| `unsupported_media_type` | 415 | Upload is not a PDF content-type |
| `invalid_pdf_signature` | 415 | Bytes do not start with `%PDF-` |
| `payload_too_large` | 413 | Over `MAX_UPLOAD_BYTES` |
| `pdf_too_many_pages` | 413 | Over `MAX_PDF_PAGES` |
| `pdf_processing_timeout` | 503 | Over `PDF_READ_TIMEOUT_SECONDS` |
| `rate_limited` | 429 | Per-client budget exceeded (`Retry-After`) |
| `unauthorized` | 401 | Missing/wrong API key |
| `server_auth_config_error` | 500 | Auth enabled but token unset |
| `required_fields_unresolved` | 422 | Required fields missing/skipped |
| `pdf_fill_failed` | 500 | Unexpected fill failure |
| `pdf_preview_failed` | 500 | Unexpected preview failure |
| `pdf_inspect_failed` | 500 | Unexpected inspect failure |
| `sample_not_found` | 404 | Bundled sample PDF missing |

Source of truth in code: `pdf_autofiller.api.errors.ERROR_CATALOG`.

## Authentication

Authentication applies to `POST /fill`, `POST /preview`, and `POST /inspect`. It is **enabled by default**
(`API_AUTH_ENABLED=true`) and can be disabled for trusted/local use by setting
`API_AUTH_ENABLED=false`.

- Header name defaults to `X-API-Key`
- The header name can be changed with `API_KEY_HEADER`
- The expected token value is provided through `API_AUTH_TOKEN`
