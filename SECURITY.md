# Security Policy

## Supported Versions

This project is currently pre-1.0 and maintained on the `main` branch.
Security fixes are applied to the latest code only.

## Reporting a Vulnerability

Do **not** open a public issue for security reports.

Use [GitHub Private Vulnerability Reporting](https://github.com/lindseystead/ai-pdf-autofiller/security/advisories/new):

1. Open a private advisory with a clear description, reproduction steps or proof of concept, and an impact assessment.
2. Expect an initial response within 5 business days.
3. Allow a reasonable remediation window before public disclosure.

## Security Baseline

- Secrets are loaded from environment variables (for example `MODEL_PROVIDER_API_KEY`).
- `.env` files are ignored by git.
- Dependabot (`.github/dependabot.yml`) opens weekly update PRs for GitHub
  Actions and the Docker base image. For Python packages it opens security
  updates only; routine upgrades are done with `poetry update` followed by
  `make sync-requirements`, because the exported `requirements*.txt` must stay
  consistent with `poetry.lock` (the `lockfile` CI job enforces this).
- Dependency scanning is run in CI via `pip-audit`; `pypdf` and `python-multipart`
  (which parse untrusted input) are pinned to patched minimum versions.
- Static analysis checks run in CI (`ruff`, `mypy`).

## Request-Path Controls (`POST /fill`, `/preview`, `/inspect`)

- **Authentication is enabled by default and fails closed.** Disable only for
  trusted/local use via `API_AUTH_ENABLED=false`.
- **Rate limiting** per client (`RATE_LIMIT_PER_MINUTE`). Default backend is
  in-process (`RATE_LIMIT_BACKEND=memory`). Set `RATE_LIMIT_BACKEND=file` so
  workers on the same host share a flock-backed store. Multi-host deployments
  must still enforce limits at the ingress/proxy layer (or Redis). Behind a
  proxy, set `TRUST_PROXY_HEADERS=true` and `TRUSTED_PROXY_COUNT`: the client is
  read from the trusted right-hand `X-Forwarded-For` hop, so callers cannot
  forge their identity to evade the limit.
- **Upload validation:** content-type, `%PDF-` signature, byte-size cap
  (`MAX_UPLOAD_BYTES`), and page-count cap (`MAX_PDF_PAGES`).
- **DoS bounds:** PDF parsing runs off the event loop under a wall-clock timeout
  (`PDF_READ_TIMEOUT_SECONDS`); retained/forwarded text is capped
  (`MAX_PDF_TEXT_CHARS`); `user_data` nesting is capped (`MAX_USER_DATA_DEPTH`).
  Corrupt PDFs are rejected as `422 invalid_pdf`. Set a container memory limit
  as an additional backstop.
- **Header safety:** field names from untrusted PDFs are stripped of control
  and non-ASCII characters before they are echoed in response headers.
- **Temporary files** are removed on every code path, including errors, timeouts,
  and client cancellations.
- **Audit trail:** a structured, PII-free log line is emitted per fill. Shipping
  and retaining these logs is a deployment responsibility.

## Dependency Advisories

`pip-audit` runs in CI against the runtime surface (`requirements.txt`, what ships
in the Docker image) and fails the build on any finding. There are currently
**no ignored advisories** — the runtime surface audits clean. `pypdf` and
`python-multipart` (which parse untrusted input) and `starlette` (pinned `>= 1.0.1`
to resolve PYSEC-2026-161) are held at patched minimums; keep them current.

## Data Handling Notes

- This service may process sensitive form data (PII) depending on user input.
- The application does not persist uploads or generated PDFs; they live only in a
  per-request temporary directory that is deleted when the request ends.
- Provider-backed features are **opt-in** and minimize data egress: only field
  metadata, nearby page text, user-data key names, and value *type* names are
  sent — never raw user-data values or a field's current value. Disable entirely
  by leaving `MODEL_PROVIDER_API_KEY` unset and the semantic/fallback flags off.
- Operators enabling provider features should confirm an appropriate data
  processing agreement (DPA) with that provider.
- Do not use real PII in development environments unless you have explicit approval.

## Scope Clarification

- This repository does not claim compliance certifications (for example SOC 2, HIPAA, ISO 27001).
- Production deployment controls (network isolation, key management, retention policy, audit logging) are environment-specific and must be implemented by the deploying team.
- Vulnerability reports should focus on the code and documented deployment assumptions in this repository.
