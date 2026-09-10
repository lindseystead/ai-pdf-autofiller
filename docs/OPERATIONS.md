# Operations

## Runtime Configuration

Environment variables are read at process start (plain `os.getenv`). A Pydantic Settings refactor is intentionally deferred — keep configuration as documented here.

- `MODEL_PROVIDER_API_KEY`: enables semantic inference and fallback mapping
- `API_AUTH_ENABLED`: enables API key enforcement on `POST /fill`, `/preview`, and `/inspect` (**default `true`**; set `false` only for trusted/local use)
- `API_AUTH_TOKEN`: expected token value when auth is enabled
- `API_KEY_HEADER`: header name used for the incoming token
- `MAX_UPLOAD_BYTES`: maximum accepted PDF size in bytes (default 5 MiB)
- `MAX_PDF_PAGES`: maximum accepted page count, rejected before extraction (default `200`)
- `PDF_READ_TIMEOUT_SECONDS`: wall-clock budget for **full pipeline processing** on `/fill`, `/preview`, and `/inspect` — not only PDF parsing; covers enrich/map/write as well (default `20`)
- `PDF_JOB_BACKEND`: `process` (default) runs PDF work in a child process and **terminates** it on timeout; `thread` uses a soft timeout (test suite default)
- `PDF_MAX_CONCURRENT`: max in-flight PDF jobs per process (default `2`)
- `MAX_PDF_TEXT_CHARS`: cap on total extracted text retained/forwarded (default `2000000`)
- `RATE_LIMIT_PER_MINUTE`: per-client request budget for authenticated PDF POSTs; `0` disables (default `60`)
- `TRUST_PROXY_HEADERS`: when `true`, rate limiting uses the first `X-Forwarded-For` hop from a trusted reverse proxy (default `false`)
- `FORM_ALIASES_DIR`: optional directory of JSON alias packs for deterministic field mapping; must exist and be readable when set. **Caveat:** packs load lazily into the process-wide `AliasRegistry` on first use (`get_default_registry()`). Changing the directory or JSON files requires a **process restart** (or `set_default_registry(AliasRegistry.load())`) — there is no file watcher / hot reload.
- `LOG_LEVEL`: process log level (`DEBUG`, `INFO`, `WARNING`, `ERROR`)
- `LOG_FORMAT`: `text` (default) or `json` for one JSON object per log line (useful for aggregators)

## Service Behavior

- Authentication is **enabled by default** and fails closed: if `API_AUTH_ENABLED` is true but `API_AUTH_TOKEN` is unset, protected POSTs return `500 server_auth_config_error` rather than serving openly.
- Unauthenticated: `GET /`, `/playground`, `/health`, `/version`, `/samples/sample_form.pdf`.
- Protected: `POST /fill`, `/preview`, `/inspect`.
- Protected POSTs are rate limited per client and reject PDFs over the page limit or that exceed the processing time budget. Timed-out jobs are killed when `PDF_JOB_BACKEND=process` (the default).
- Uploads are read in bounded chunks so oversized files are rejected before the full body is buffered in memory.
- `GET /health` reports dependency checks (`auth`, alias packs) and returns `degraded` when auth is misconfigured.
- `POST /fill` writes uploads to a temporary working directory and returns the generated PDF directly.
- Temporary files are cleaned up after request completion or failure, including error and timeout paths.
- Responses include baseline security headers: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer` (playground HTML continues to work normally).
- Privacy: provider-backed features send field metadata and nearby page text to an external service, but **never the raw user-data values or a field's current value** — only key names and value type names are shared. Disable these features by leaving `MODEL_PROVIDER_API_KEY` unset and the semantic/fallback flags off.

## Rate limiting (single worker vs multi-worker)

The in-process sliding-window limiter is suitable for a **single uvicorn worker**. It does **not** share state across workers or replicas.

For multi-worker or multi-instance deployments, enforce limits **outside** the app:

1. **Ingress / reverse proxy** — nginx `limit_req`, Envoy rate limits, Cloudflare, AWS API Gateway, etc.
2. **Shared store** — Redis (or similar) token bucket / sliding window in front of or beside the app.
3. Keep `RATE_LIMIT_PER_MINUTE` as a last-resort per-process guard, or set it to `0` when ingress already enforces a global budget.

Also set `TRUST_PROXY_HEADERS=true` only when a trusted proxy strips/spoofs `X-Forwarded-For` correctly; otherwise clients can bypass per-IP limits.

## Audit Logging

- Each successful fill emits one structured, PII-free `audit action=fill` log line containing the request ID, whether auth was enabled, the optional features used, and field counts (total/written/review-skipped/empty-skipped/unwritable/missing). No field names or user values are logged.
- Set `LOG_FORMAT=json` to emit JSON log lines for shipping to a log aggregator.
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

One-command local try (auth off):

```bash
docker compose up --build
```

For trusted local experimentation only, you can disable auth with
`-e API_AUTH_ENABLED=false`.

The container runs as a non-root user and exposes a Docker `HEALTHCHECK` against `/health`.

## GitHub Pages (one-time setup)

The landing page source is in `docs/site/`. A repo admin must enable Pages once:

1. **Settings → Pages → Build and deployment**
2. Set **Source** to **GitHub Actions**
3. Merge or push to `main` (the deploy workflow runs when `docs/site/` changes)

Until Pages is enabled, `.github/workflows/pages.yml` **skips the deploy with a warning** instead of failing CI. After enablement, the same workflow publishes to `https://lindseystead.github.io/ai-pdf-autofiller/`.

## PyPI publish (deferred)

**Not part of the automatic Release path.** Supported installs are GitHub Release wheels (`make install-release`), editable/`pip install -e .`, and GHCR.

`.github/workflows/publish-pypi.yml` is **manual** (`workflow_dispatch` only) and uses Trusted Publishing (OIDC) with `environment: pypi` — no API token. When you have time, add a pending publisher on [PyPI](https://pypi.org/manage/account/publishing/) (Owner `lindseystead`, Repo `ai-pdf-autofiller`, Workflow `publish-pypi.yml`, Environment `pypi`), then `gh workflow run publish-pypi.yml --ref main`. Details: [RELEASE.md](RELEASE.md).

## Deployment Assumptions

- TLS termination, ingress policy, and network isolation are handled by the deployment environment.
- Secret storage and rotation are handled by the deployment environment.
- Audit logging, retention policy, and data classification remain deployment-specific responsibilities.
