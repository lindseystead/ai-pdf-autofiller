# Operations

## Runtime Configuration

- `MODEL_PROVIDER_API_KEY`: enables semantic inference and fallback mapping
- `API_AUTH_ENABLED`: enables API key enforcement on `POST /fill`
- `API_AUTH_TOKEN`: expected token value when auth is enabled
- `API_KEY_HEADER`: header name used for the incoming token
- `MAX_UPLOAD_BYTES`: maximum accepted PDF size in bytes
- `LOG_LEVEL`: process log level (`DEBUG`, `INFO`, `WARNING`, `ERROR`)

## Service Behavior

- `GET /health` and `GET /version` are always unauthenticated.
- `POST /fill` writes uploads to a temporary working directory and returns the generated PDF directly.
- Temporary files are cleaned up after request completion or failure.
- If optional provider-backed features are enabled, field metadata and nearby page text may be sent to an external service.

## Container Usage

Build:

```bash
docker build -t pdf-autofiller .
```

Run:

```bash
docker run --rm -p 8000:8000 \
  -e API_AUTH_ENABLED=false \
  pdf-autofiller
```

The container runs as a non-root user and exposes a Docker `HEALTHCHECK` against `/health`.

## Deployment Assumptions

- TLS termination, ingress policy, and network isolation are handled by the deployment environment.
- Secret storage and rotation are handled by the deployment environment.
- Audit logging, retention policy, and data classification remain deployment-specific responsibilities.
