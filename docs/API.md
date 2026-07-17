# API Reference

## Endpoints

### `GET /playground`

Serves the browser playground UI for trying fills without curl.

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
  "version": "0.4.3",
  "checks": {
    "auth": "disabled",
    "alias_directory": "/app/src/pdf_autofiller/form_aliases",
    "alias_pack_count": "2"
  }
}
```

`status` is `degraded` when auth is enabled but `API_AUTH_TOKEN` is unset (`checks.auth` = `misconfigured`). Alias pack health is reported via `checks.alias_directory` and `checks.alias_pack_count`.

### `GET /version`

Returns service identity and version.

Example:

```bash
curl -s http://localhost:8000/version
```

### `POST /fill`

Accepts a multipart form upload and returns a filled PDF.

Required form fields:

- `pdf_file`: the source PDF upload
- `user_data`: a JSON object encoded as form text

Optional form fields:

- `strict`: when `true`, disables fallback mapping
- `allow_fallback_mapping`: when `true`, allows fallback mapping for unresolved high-value fields
- `use_semantic_inference`: when `true`, enables the semantic inference step before mapping

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

Authentication applies only to `POST /fill`. It is **enabled by default**
(`API_AUTH_ENABLED=true`) and can be disabled for trusted/local use by setting
`API_AUTH_ENABLED=false`.

- Header name defaults to `X-API-Key`
- The header name can be changed with `API_KEY_HEADER`
- The expected token value is provided through `API_AUTH_TOKEN`
