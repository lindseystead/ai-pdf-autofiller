# Security Policy

## Supported Versions

This project is currently pre-1.0 and maintained on the `main` branch.
Security fixes are applied to the latest code only.

## Reporting a Vulnerability

If you discover a security issue, please do not open a public issue.

1. Email the maintainer at `wysel17@mytru.ca`.
2. Include a clear description of the issue, reproduction steps or proof of concept, and an impact assessment.
3. Expect an initial response within 5 business days.
4. Allow a reasonable remediation window before public disclosure.

## Security Baseline

- Secrets are loaded from environment variables (for example `MODEL_PROVIDER_API_KEY`).
- `.env` files are ignored by git.
- Dependency scanning is run in CI via `pip-audit`; `pypdf` and `python-multipart`
  (which parse untrusted input) are pinned to patched minimum versions.
- Static analysis checks run in CI (`ruff`, `mypy`).

## Request-Path Controls (`POST /fill`)

- **Authentication is enabled by default and fails closed.** Disable only for
  trusted/local use via `API_AUTH_ENABLED=false`.
- **Rate limiting** per client (`RATE_LIMIT_PER_MINUTE`). The built-in limiter is
  in-process; multi-worker/multi-instance deployments must enforce limits at the
  ingress/proxy layer.
- **Upload validation:** content-type, `%PDF-` signature, byte-size cap
  (`MAX_UPLOAD_BYTES`), and page-count cap (`MAX_PDF_PAGES`).
- **DoS bounds:** PDF parsing runs off the event loop under a wall-clock timeout
  (`PDF_READ_TIMEOUT_SECONDS`); retained/forwarded text is capped
  (`MAX_PDF_TEXT_CHARS`). Set a container memory limit as an additional backstop.
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
