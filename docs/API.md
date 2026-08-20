# API Reference

All routes are served under `/v1`. The unversioned paths (`/fill`, `/health`)
remain as aliases so existing callers keep working, but new consumers should use
the versioned form.

For local use the [CLI](CLI.md) does everything the API does without a server.

## Endpoints

### `GET /playground`

Serves the browser playground UI for trying fills without curl.

### `GET /v1/health`

Returns service health metadata.

Example:

```bash
curl -s http://localhost:8000/v1/health
```

Example response:

```json
{
  "status": "ok",
  "service": "pdf-autofiller",
  "version": "0.5.0",
  "checks": {
    "auth": "disabled",
    "semantics_cache_entries": "0",
    "alias_directory": "/app/src/pdf_autofiller/form_aliases",
    "alias_pack_count": "4"
  }
}
```

`status` is `degraded` when auth is enabled but `API_AUTH_TOKEN` is unset (`checks.auth` = `misconfigured`). Alias pack problems surface under `checks.alias_packs`.

### `GET /v1/version`

Returns service identity and version.

Example:

```bash
curl -s http://localhost:8000/v1/version
```

### `POST /v1/inspect`

Reports a form's fields and previews what a fill would do. **Writes nothing and
returns no document.** This is how you discover what a form wants without
guessing key names.

Required form fields:

- `pdf_file`: the source PDF upload

Optional form fields:

- `user_data`: a JSON object encoded as form text; when supplied, the response
  includes a dry-run mapping
- `overrides`: JSON object of `field_name -> value`
- `template`, `profile`: names of stored entries to apply
- `use_semantic_inference`: enable the inference step before mapping

Example:

```bash
curl -s -X POST http://localhost:8000/v1/inspect \
  -F "pdf_file=@form.pdf;type=application/pdf" \
  -F 'user_data={"firstname":"Jane"}'
```

Response (abridged):

```json
{
  "metadata": { "num_pages": 1 },
  "fingerprint": "922efc3ca405cfeb28d29c644deff70a",
  "fields": [
    {
      "field": { "name": "txtFirstName", "field_type": "text", "required": true, "options": [] },
      "semantics": { "semantic_meaning": "first_name", "expected_data_type": "string" }
    }
  ],
  "mapping": { "decisions": [], "missing_required": ["txtLastName"], "unmapped_user_keys": [] },
  "would_write": ["txtFirstName"],
  "would_skip": ["txtLastName"]
}
```

`fields[].field.options` lists the permitted values for a choice field or the
export states of a checkbox, so a caller can supply a legal value.

### `POST /v1/fill`

Accepts a multipart form upload and returns a filled PDF.

Required form fields:

- `pdf_file`: the source PDF upload
- `user_data`: a JSON object encoded as form text

Optional form fields:

- `strict`: when `true`, disables fallback mapping
- `allow_fallback_mapping`: when `true`, allows fallback mapping for unresolved high-value fields
- `use_semantic_inference`: when `true`, enables the semantic inference step before mapping
- `flatten`: when `true`, stamps values into the page and removes the interactive
  form so the result cannot be edited downstream
- `allow_key_reuse`: when `false`, each data key fills at most one field
- `overrides`: JSON object of `field_name -> value` that wins over any matching
- `template`, `profile`: names of stored entries to apply
- `response_format`: `pdf` (default) or `json`

`user_data` is optional when a `profile` or `template` supplies the values, but a
request with no data source at all is rejected (`no_fill_data`) rather than
returning an unchanged document that looks like a successful fill.

With `response_format=json` (or an `Accept: application/json` header) the response
is a JSON object carrying the full fill report, the mapping decisions, and the
document base64-encoded under `pdf_base64`. The header-based report below is
ASCII-stripped and length-capped; JSON mode is the complete one.

Example:

```bash
curl -s -X POST http://localhost:8000/fill \
  -F "pdf_file=@samples/sample_form.pdf;type=application/pdf" \
  -F 'user_data={"firstname":"Alex","lastname":"Example","dob":"1990-01-15"}' \
  -F "strict=true" \
  -o filled.pdf
```

On success the response body is the generated PDF (`application/pdf`).

Successful responses also include fill-outcome headers so clients can detect
fields that were dropped instead of silently losing them:

- `X-PDF-Fields-Written`: count of fields that received a value
- `X-PDF-Fields-Skipped-Review`: comma-separated field names skipped because the mapping was flagged for review
- `X-PDF-Fields-Skipped-Empty`: comma-separated field names skipped because the mapped value was empty

Checkbox and radio (`/Btn`) fields are written using their PDF state names, so
boolean-style inputs (`true`/`yes`/`1`/`on`) correctly toggle the control.

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

Common error codes:

- `request_validation_error`
- `invalid_user_data_json`
- `invalid_user_data_type`
- `unsupported_media_type`
- `invalid_pdf_signature`
- `payload_too_large`
- `pdf_too_many_pages`
- `pdf_processing_timeout`
- `rate_limited`
- `unauthorized`
- `server_auth_config_error`
- `required_fields_unresolved`
- `pdf_fill_failed`

## Authentication

Authentication applies only to `POST /v1/fill` and `POST /v1/inspect`. It is **enabled by default**
(`API_AUTH_ENABLED=true`) and can be disabled for trusted/local use by setting
`API_AUTH_ENABLED=false`.

- Header name defaults to `X-API-Key`
- The header name can be changed with `API_KEY_HEADER`
- The expected token value is provided through `API_AUTH_TOKEN`

### Templates and profiles

Stored server-side under the state directory (`PDF_AUTOFILLER_STATE_DIR`).

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/v1/templates` | List stored templates |
| `PUT` | `/v1/templates/{name}` | Create or replace a template |
| `GET` | `/v1/templates/{name}` | Fetch one template |
| `DELETE` | `/v1/templates/{name}` | Delete a template |
| `GET` | `/v1/profiles` | List profiles — names and key names only, never the data |
| `PUT` | `/v1/profiles/{name}` | Create or replace a profile |
| `GET` | `/v1/profiles/{name}` | Fetch one profile, including its data |
| `DELETE` | `/v1/profiles/{name}` | Delete a profile |

The profile index deliberately returns only names and key names; profiles hold
personal data, so the values require asking for a profile by name.

## Error contract

Every error shares one shape:

```json
{
  "detail": {
    "error": {
      "code": "required_fields_unresolved",
      "message": "Missing required fields: txtLastName",
      "details": { "missing_fields": ["txtLastName"], "skipped_fields": [] }
    }
  }
}
```

Match on `code`, not on `message` — messages may be reworded, codes are stable.

| Code | Status | Meaning |
|------|--------|---------|
| `unauthorized` | 401 | Missing or wrong API token |
| `server_auth_config_error` | 500 | Auth is enabled but no token is configured |
| `rate_limited` | 429 | Per-client request budget exceeded |
| `unsupported_media_type` | 415 | Upload was not declared as a PDF |
| `invalid_pdf_signature` | 415 | Upload does not begin with `%PDF-` |
| `payload_too_large` | 413 | PDF exceeds `MAX_UPLOAD_BYTES` |
| `user_data_too_large` | 413 | JSON exceeds size, key-count, or nesting limits |
| `invalid_user_data_json` | 422 | `user_data` is not valid JSON |
| `invalid_user_data_type` | 422 | `user_data` is not a JSON object |
| `no_fill_data` | 422 | No `user_data`, profile, or overrides supplied |
| `pdf_encrypted` | 422 | Password-protected document |
| `pdf_xfa_unsupported` | 422 | XFA form; not fillable as an AcroForm |
| `pdf_no_form_fields` | 422 | No fillable fields — likely scanned or already flattened |
| `pdf_parse_failed` | 422 | Malformed PDF |
| `pdf_too_many_pages` | 413 | Exceeds `MAX_PDF_PAGES` |
| `required_fields_unresolved` | 422 | A required field had no usable value |
| `template_not_found` | 404 | Named template does not exist |
| `profile_not_found` | 404 | Named profile does not exist |
| `pdf_processing_timeout` | 503 | Parsing exceeded `PDF_READ_TIMEOUT_SECONDS` |

## Response headers on a fill

| Header | Meaning |
|--------|---------|
| `X-PDF-Fields-Written` | Count of fields that received a value |
| `X-PDF-Fields-Skipped-Review` | Fields skipped because the mapping was ambiguous |
| `X-PDF-Fields-Skipped-Empty` | Fields skipped because the value was empty |
| `X-PDF-Fields-Skipped-Invalid` | Values illegal for the field type (bad choice, signature field) |
| `X-PDF-Flattened` | Whether the interactive form was removed |
| `X-Request-ID` | Echoes a supplied request ID, or a generated one |
