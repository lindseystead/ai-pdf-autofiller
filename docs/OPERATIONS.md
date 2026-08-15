# Operations

## Runtime Configuration

- `MODEL_PROVIDER_API_KEY`: enables semantic inference and fallback mapping
- `API_AUTH_ENABLED`: enables API key enforcement on `POST /fill` (**default `true`**; set `false` only for trusted/local use)
- `API_AUTH_TOKEN`: expected token value when auth is enabled
- `API_KEY_HEADER`: header name used for the incoming token
- `MAX_UPLOAD_BYTES`: maximum accepted PDF size in bytes (default 5 MiB)
- `MAX_PDF_PAGES`: maximum accepted page count, rejected before extraction (default `200`)
- `PDF_READ_TIMEOUT_SECONDS`: wall-clock budget for PDF parsing/extraction (default `20`)
- `SEMANTIC_TIMEOUT_SECONDS`: **additional** budget granted when a request opts into provider-backed features (default `45`). Model latency is not parsing time; charging both to one clock made large forms time out as soon as inference was enabled.
- `PDF_WORKER_THREADS`: size of the bounded pool that runs PDF work (default `4`)
- `PDF_QUEUE_DEPTH`: how many additional requests may wait for a worker before the service sheds load with `503 server_busy` (default `4`)
- `MAX_PDF_TEXT_CHARS`: cap on total extracted text retained/forwarded (default `2000000`)
- `RATE_LIMIT_PER_MINUTE`: per-client request budget for `POST /fill`; `0` disables (default `60`)
- `TRUST_PROXY_HEADERS`: when `true`, rate limiting uses `X-Forwarded-For` / `X-Real-IP` from a trusted reverse proxy (default `false`)
- `FORM_ALIASES_DIR`: optional directory of JSON alias packs for deterministic field mapping; must exist and be readable when set
- `LOG_LEVEL`: process log level (`DEBUG`, `INFO`, `WARNING`, `ERROR`)

### Model Provider Configuration

These apply only when the optional provider path is enabled. Nothing here is
consulted on the default deterministic path.

- `MODEL_NAME`: model to call (default `gpt-4o-mini`). Pinned deliberately — an unpinned alias would let the provider change inference behavior underneath a deterministic-first service.
- `MODEL_TEMPERATURE`: sampling temperature (default `0.0`). Semantic inference and fallback mapping are classification tasks; sampling adds variance without benefit.
- `MODEL_TIMEOUT_SECONDS`: per-call timeout handed to the provider SDK (default `15`)
- `MODEL_MAX_RETRIES`: retries for transient provider failures (default `2`)
- `MODEL_RETRY_BACKOFF_SECONDS`: base delay for exponential backoff between retries (default `0.5`)
- `MODEL_SEMANTIC_BATCH_SIZE`: fields described per inference call (default `40`). Batching is what keeps a form to one or two round trips instead of one per field.
- `MODEL_CONTEXT_CHAR_LIMIT`: untrusted page text forwarded per field (default `500`)
- `MODEL_CONFIDENCE_CEILING`: cap applied to any confidence a model reports about its own output (default `0.75`)
- `MAPPING_REVIEW_THRESHOLD`: confidence at or above which a decision is written without review (default `0.80`)

The ceiling defaults **below** the review threshold on purpose: model
self-reported confidence is not calibrated, so it must not be able to clear a
review gate by itself. With defaults, every model-derived mapping is flagged
`requires_review` and is surfaced rather than written. Raising
`MODEL_CONFIDENCE_CEILING` above `MAPPING_REVIEW_THRESHOLD` opts into writing
model-chosen values unattended; do that only if you accept that risk.

## Service Behavior

- Authentication is **enabled by default** and fails closed: if `API_AUTH_ENABLED` is true but `API_AUTH_TOKEN` is unset, `POST /fill` returns `500 server_auth_config_error` rather than serving openly.
- `GET /health` and `GET /version` are always unauthenticated.
- `POST /fill` is rate limited per client and rejects PDFs over the page limit or that exceed the processing time budget.
- PDF work runs on a bounded worker pool. Because a Python worker thread cannot be cancelled, a timed-out job keeps running and **keeps holding its worker slot until it finishes** — so timed-out work cannot pile up invisibly. Requests that arrive with no capacity are shed with `503 server_busy`.
- A job that outlives its request retains ownership of its temporary directory; cleanup happens when the job ends, so files are never deleted from under a running worker.
- Uploads are read in bounded chunks so oversized files are rejected before the full body is buffered in memory.
- `GET /health` reports dependency checks (`auth`, `model_provider`, `model_name`, alias packs) and returns `degraded` when auth is misconfigured.
- `POST /fill` writes uploads to a temporary working directory and returns the generated PDF directly.
- Temporary files are cleaned up after request completion or failure, including error and timeout paths.
- Privacy: provider-backed features send field metadata and nearby page text to an external service, but **never the raw user-data values or a field's current value** — only key names and value type names are shared. Disable these features by leaving `MODEL_PROVIDER_API_KEY` unset and the semantic/fallback flags off.
- The in-process rate limiter suits a single worker; for multi-worker or multi-instance deployments, enforce limits at the ingress/proxy layer.

## Audit Logging

- Each successful fill emits one structured, PII-free `audit action=fill` log line containing the request ID, whether auth was enabled, field counts (total/written/failed/review-skipped/empty-skipped/missing), and what the model path actually did. No field names or user values are logged.
- The model fields distinguish **requested** from **applied**: `semantic_requested` / `semantic_applied`, `fallback_requested` / `fallback_applied`, plus `fields_inferred`, `model`, `provider_calls`, `provider_retries`, `provider_failures`, `tokens`, and `degraded`. A run that asked for inference and silently fell back to deterministic behavior is therefore distinguishable from one where the model ran — previously the log recorded only the requested flag.
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
