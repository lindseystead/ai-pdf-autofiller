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

## Landing page

Static site: [docs/site/](site/). Source images live in [assets/](assets/).

**GitHub Pages:** enable Settings → Pages → Source = **GitHub Actions**, then the
`Deploy GitHub Pages` workflow publishes `docs/site/`. Until then, leave the
repo homepage blank (a 404 hurts recruiter first impressions).

**Social preview:** upload `docs/assets/social-preview.png` under Settings →
General → Social preview.

To update GitHub **description** and **topics** (search visibility on GitHub):

```bash
bash scripts/apply-repo-metadata.sh
```

Requires `gh` CLI logged in as a repo admin.

Optional: upload `docs/assets/social-preview.png` under **Settings → General → Social preview** for link previews on Twitter/Slack/Discord.
