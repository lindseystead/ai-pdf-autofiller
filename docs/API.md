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
  "version": "0.5.0",
  "checks": {
    "auth": "disabled",
    "model_provider": "not_configured",
    "model_name": "gpt-4o-mini",
    "alias_directory": "/app/src/pdf_autofiller/form_aliases",
    "alias_pack_count": "2"
  }
}
```

`status` is `degraded` when auth is enabled but `API_AUTH_TOKEN` is unset (`checks.auth` = `misconfigured`). `checks.model_provider` reports whether a provider credential is configured; it does not imply any given request used the model path. Alias pack resolution surfaces under `checks.alias_directory` and `checks.alias_pack_count`.

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

Both provider-backed options require `MODEL_PROVIDER_API_KEY` to be configured
server-side. If it is not, the request still succeeds using deterministic
matching, and `X-PDF-Semantic-Inference: degraded` reports that the model path
did not run.

A request that opts into either option is granted an additional time budget
(`SEMANTIC_TIMEOUT_SECONDS`) on top of the PDF parsing budget, because model
latency is not parsing time.

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

- `X-PDF-Fields-Written`: count of fields **verified present in the output document**. The service re-reads the PDF it produced rather than assuming a write succeeded.
- `X-PDF-Fields-Failed`: comma-separated field names that were written but could not be verified in the output. Verification fails closed: if the output cannot be re-read at all, every intended field is reported here rather than as written.
- `X-PDF-Fields-Skipped-Review`: comma-separated field names skipped because the mapping was flagged for review
- `X-PDF-Fields-Skipped-Empty`: comma-separated field names skipped because the mapped value was empty
- `X-PDF-Semantic-Inference`: what the optional model path actually did — `off`, `applied`, `degraded-partial`, or `degraded`. **`degraded` means inference was requested but did not run** (no provider configured, or the provider failed) and the fill used deterministic semantics.
- `X-PDF-Provider-Calls`: number of successful provider round trips for this request
- `X-PDF-Provider-Tokens`: total tokens billed for this request

A client that enables `use_semantic_inference` should check
`X-PDF-Semantic-Inference` rather than assuming the flag took effect.

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
- `server_busy` (503; PDF worker capacity is saturated — retry shortly)
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
