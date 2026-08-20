# Operations

This page covers running the HTTP service. For local, single-user work the
[CLI](CLI.md) needs none of this — no server, no token, no configuration.

## Runtime Configuration

- `MODEL_PROVIDER_API_KEY`: enables semantic inference and fallback mapping
- `API_AUTH_ENABLED`: enables API key enforcement on `POST /fill` (**default `true`**; set `false` only for trusted/local use)
- `API_AUTH_TOKEN`: expected token value when auth is enabled
- `API_KEY_HEADER`: header name used for the incoming token
- `MAX_UPLOAD_BYTES`: maximum accepted PDF size in bytes (default 5 MiB)
- `MAX_PDF_PAGES`: maximum accepted page count, rejected before extraction (default `200`)
- `PDF_READ_TIMEOUT_SECONDS`: wall-clock budget for PDF parsing/extraction (default `20`)
- `MAX_PDF_TEXT_CHARS`: cap on total extracted text retained/forwarded (default `2000000`)
- `RATE_LIMIT_PER_MINUTE`: per-client request budget for `POST /fill`; `0` disables (default `60`)
- `TRUST_PROXY_HEADERS`: when `true`, rate limiting uses `X-Forwarded-For` / `X-Real-IP` from a trusted reverse proxy (default `false`)
- `FORM_ALIASES_DIR`: optional directory of JSON alias packs for deterministic field mapping; must exist and be readable when set
- `LOG_LEVEL`: process log level (`DEBUG`, `INFO`, `WARNING`, `ERROR`)
- `MAX_USER_DATA_BYTES`: maximum accepted `user_data` JSON size in bytes (default `262144`)
- `MAX_USER_DATA_KEYS`: maximum total keys across nested `user_data` (default `500`)
- `MAX_USER_DATA_DEPTH`: maximum nesting depth in `user_data` (default `8`)
- `PDF_AUTOFILLER_STATE_DIR`: where templates and profiles are stored (default `~/.pdf-autofiller`)
- `CORS_ALLOW_ORIGINS`: comma-separated origins allowed to call the API from a browser; empty disables CORS entirely (default empty — there is deliberately no wildcard)
- `SEMANTICS_CACHE_SIZE`: how many forms' inferred semantics to keep in memory; `0` disables (default `128`)
- `MODEL_PROVIDER_MODEL`: model used for semantic inference (default `gpt-4o-mini`)
- `MODEL_PROVIDER_TIMEOUT_SECONDS`: per-call provider timeout (default `30`)
- `MODEL_PROVIDER_MAX_RETRIES`: retries on transient provider failure (default `2`)
- `MODEL_PROVIDER_BATCH_SIZE`: fields per inference request; larger forms are split across calls (default `40`)

A malformed value (for example a non-numeric `MAX_UPLOAD_BYTES`) raises a
readable configuration error at startup rather than a traceback mid-import.

## Service Behavior

- Authentication is **enabled by default** and fails closed: if `API_AUTH_ENABLED` is true but `API_AUTH_TOKEN` is unset, `POST /fill` returns `500 server_auth_config_error` rather than serving openly.
- `GET /health` and `GET /version` are always unauthenticated.
- `POST /v1/fill` and `POST /v1/inspect` are rate limited per client and reject PDFs over the page limit or that exceed the processing time budget.
- PDF parsing runs in a **killable child process** under a wall-clock timeout. A thread cannot be interrupted in CPython, so a hostile document under a thread-based timeout would return `503` while continuing to consume a worker forever. The child process also contains parser memory blowups and hard crashes.
- The JSON accompanying an upload is bounded in bytes, key count, and nesting depth, not just the PDF itself.
- Uploads are read in bounded chunks so oversized files are rejected before the full body is buffered in memory.
- `GET /v1/health` reports dependency checks (`auth`, alias pack count and directory, semantics cache occupancy) and returns `degraded` when auth is misconfigured.
- CORS is **off unless configured**. A wildcard default would let any page on the internet drive a deployment a browser has already authenticated.
- `POST /fill` writes uploads to a temporary working directory and returns the generated PDF directly.
- Temporary files are cleaned up after request completion or failure, including error and timeout paths.
- Privacy: provider-backed features send field metadata and nearby page text to an external service, but **never the raw user-data values or a field's current value** — only key names and value type names are shared. Disable these features by leaving `MODEL_PROVIDER_API_KEY` unset and the semantic/fallback flags off.
- The in-process rate limiter suits a single worker; for multi-worker or multi-instance deployments, enforce limits at the ingress/proxy layer.

## Audit Logging

- Each successful fill emits one structured, PII-free `audit action=fill` log line containing the request ID, whether auth was enabled, the optional features used, whether the output was flattened, and field counts (total / written / review-skipped / empty-skipped / invalid-skipped / missing-required). No field names or user values are logged.
- These lines are the application-level audit trail. Shipping them to a durable, access-controlled store and setting a retention policy are deployment responsibilities.

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

## GitHub Pages (one-time setup)

The landing page source is in `docs/site/`. A repo admin must enable Pages once:

1. **Settings → Pages → Build and deployment**
2. Set **Source** to **GitHub Actions**
3. Merge or push to `main` (the deploy workflow runs when `docs/site/` changes)

Published URL: `https://lindseystead.github.io/ai-pdf-autofiller/`

## PyPI publish

Add `PYPI_API_TOKEN` as a repository secret. The publish workflow runs on each GitHub Release; without the secret it completes with a warning and wheels remain on GitHub Releases.

## Deployment Assumptions

- TLS termination, ingress policy, and network isolation are handled by the deployment environment.
- Secret storage and rotation are handled by the deployment environment.
- Audit logging, retention policy, and data classification remain deployment-specific responsibilities.
