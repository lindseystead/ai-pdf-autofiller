# Documentation Index

Supporting documentation for the PDF Autofiller service. Claims in these docs match code and CI fixtures — not future plans.

## Core docs

| Doc | Description |
|-----|-------------|
| [API.md](API.md) | Endpoint contracts, errors, and response headers |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Module boundaries, data flow, extension points |
| [OPERATIONS.md](OPERATIONS.md) | Runtime configuration and deployment |
| [RELEASE.md](RELEASE.md) | Tag → GHCR / Release assets (PyPI optional/manual) |
| [TESTING.md](TESTING.md) | Local validation and CI |
| [PURPOSE.md](PURPOSE.md) | Problem statement, scope, intended usage |
| [FAQ.md](FAQ.md) | Comparisons, AcroForm vs scan, auth, local vs HTTP |

## Related

| Doc | Description |
|-----|-------------|
| [integrations/](integrations/) | n8n (importable workflow), Zapier, LangChain |
| [assets/demo-terminal.txt](assets/demo-terminal.txt) | Captured inspect → preview → fill transcript |
| [../README.md](../README.md) | Project overview and quick start |
| [../CONTRIBUTING.md](../CONTRIBUTING.md) | Contributor setup and PR expectations |
| [../CODE_OF_CONDUCT.md](../CODE_OF_CONDUCT.md) | Community standards |
| [../SECURITY.md](../SECURITY.md) | Vulnerability reporting |
| [../samples/README.md](../samples/README.md) | Sample PDFs and corpus notes |
| [../recipes/](../recipes/) | Worked examples against shipped fixtures |

## Landing page / GitHub storefront

Static site: [docs/site/](site/). Source images live in [assets/](assets/).

**Claude / admin handoff:** remaining GitHub About / homepage / social-preview /
stale-PR work is documented in
[GITHUB_STOREFRONT_HANDOFF.md](GITHUB_STOREFRONT_HANDOFF.md). Code polish through
**v0.6.3** is already on `main`; only Settings/admin steps are left.

Quick admin commands (your `gh` login, not a cloud-agent token):

```bash
bash scripts/apply-repo-metadata.sh
bash scripts/fix-github-storefront.sh
```

Then upload `docs/assets/social-preview.png` under **Settings → General → Social preview**.
Enable Pages (Actions) before setting a homepage URL, or leave homepage blank.
