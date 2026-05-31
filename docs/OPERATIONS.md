# Operations

## Runtime Configuration

- `MODEL_PROVIDER_API_KEY`: enables semantic inference and fallback mapping
- `API_AUTH_ENABLED`: enables API key enforcement on `POST /fill` (**default `true`**; set `false` only for trusted/local use)
- `API_AUTH_TOKEN`: expected token value when auth is enabled
- `API_KEY_HEADER`: header name used for the incoming token
- `MAX_UPLOAD_BYTES`: maximum accepted PDF size in bytes (default 5 MiB)
- `MAX_PDF_PAGES`: maximum accepted page count, rejected before extraction (default `200`)
- `PDF_READ_TIMEOUT_SECONDS`: wall-clock budget for PDF parsing/extraction (default `20`)
- `RATE_LIMIT_PER_MINUTE`: per-client request budget for `POST /fill`; `0` disables (default `60`)
- `LOG_LEVEL`: process log level (`DEBUG`, `INFO`, `WARNING`, `ERROR`)

## Service Behavior

- Authentication is **enabled by default** and fails closed: if `API_AUTH_ENABLED` is true but `API_AUTH_TOKEN` is unset, `POST /fill` returns `500 server_auth_config_error` rather than serving openly.
- `GET /health` and `GET /version` are always unauthenticated.
- `POST /fill` is rate limited per client and rejects PDFs over the page limit or that exceed the processing time budget.
- `POST /fill` writes uploads to a temporary working directory and returns the generated PDF directly.
- Temporary files are cleaned up after request completion or failure, including error and timeout paths.
- Privacy: provider-backed features send field metadata and nearby page text to an external service, but **never the raw user-data values or a field's current value** — only key names and value type names are shared. Disable these features by leaving `MODEL_PROVIDER_API_KEY` unset and the semantic/fallback flags off.
- The in-process rate limiter suits a single worker; for multi-worker or multi-instance deployments, enforce limits at the ingress/proxy layer.

## Container Usage

Build:

```bash
docker build -t pdf-autofiller .
```

Run:

```bash
docker run --rm -p 8000:8000 \
  -e API_AUTH_ENABLED=true \
  -e API_AUTH_TOKEN=replace_with_strong_random_value \
  pdf-autofiller
```

For trusted local experimentation only, you can disable auth with
`-e API_AUTH_ENABLED=false`.

The container runs as a non-root user and exposes a Docker `HEALTHCHECK` against `/health`.

## Deployment Assumptions

- TLS termination, ingress policy, and network isolation are handled by the deployment environment.
- Secret storage and rotation are handled by the deployment environment.
- Audit logging, retention policy, and data classification remain deployment-specific responsibilities.
