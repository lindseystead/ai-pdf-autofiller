# Documentation Index

Supporting documentation for the PDF Autofiller service.

## Core docs

| Doc | Description |
|-----|-------------|
| [API.md](API.md) | Endpoint contracts, errors, and response headers |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Module boundaries, data flow, extension points |
| [OPERATIONS.md](OPERATIONS.md) | Runtime configuration and deployment |
| [TESTING.md](TESTING.md) | Local validation and CI |
| [PURPOSE.md](PURPOSE.md) | Problem statement, scope, intended usage |

## Related

| Doc | Description |
|-----|-------------|
| [integrations/](integrations/) | n8n, Zapier, and LangChain guides |
| [assets/demo-terminal.txt](assets/demo-terminal.txt) | Example terminal workflow output |
| [../README.md](../README.md) | Project overview and quick start |
| [../CONTRIBUTING.md](../CONTRIBUTING.md) | Contributor setup and PR expectations |
| [../CODE_OF_CONDUCT.md](../CODE_OF_CONDUCT.md) | Community standards |
| [../SECURITY.md](../SECURITY.md) | Vulnerability reporting |

## Landing page

Static site: [docs/site/](site/). Source images live in [assets/](assets/).

To update GitHub **description** and **topics** (search visibility on GitHub):

```bash
bash scripts/apply-repo-metadata.sh
```

Requires `gh` CLI logged in as a repo admin.

Optional: upload `docs/assets/social-preview.png` under **Settings → General → Social preview** for link previews on Twitter/Slack/Discord.
