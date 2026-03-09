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
- Dependency scanning is run in CI via `pip-audit`.
- Static analysis checks run in CI (`ruff`, `mypy`).

## Data Handling Notes

- This project may process sensitive form data depending on user input.
- If optional provider-backed features are enabled, prompt content can be sent to external services.
- Do not use real PII in development environments unless you have explicit approval.

## Scope Clarification

- This repository does not claim compliance certifications (for example SOC 2, HIPAA, ISO 27001).
- Production deployment controls (network isolation, key management, retention policy, audit logging) are environment-specific and must be implemented by the deploying team.
- Vulnerability reports should focus on the code and documented deployment assumptions in this repository.
