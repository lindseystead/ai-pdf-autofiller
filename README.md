<div align="center">

<img src="docs/assets/social-preview.png" alt="PDF Autofiller — Fill any AcroForm PDF from JSON" width="800" />

# PDF Autofiller

**Fill any AcroForm PDF from JSON — no manual field mapping.**

Open-source FastAPI service · browser playground · Python SDK · Docker image

[![CI](https://github.com/lindseystead/ai-pdf-autofiller/actions/workflows/test.yml/badge.svg)](https://github.com/lindseystead/ai-pdf-autofiller/actions/workflows/test.yml)
[![Release](https://img.shields.io/github/v/release/lindseystead/ai-pdf-autofiller?label=release)](https://github.com/lindseystead/ai-pdf-autofiller/releases)
[![GitHub stars](https://img.shields.io/github/stars/lindseystead/ai-pdf-autofiller?style=social)](https://github.com/lindseystead/ai-pdf-autofiller/stargazers)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%20%7C%203.12-blue.svg)](https://www.python.org/downloads/)
[![Coverage](https://img.shields.io/badge/coverage-%E2%89%A585%25-brightgreen.svg)](https://github.com/lindseystead/ai-pdf-autofiller)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Docker](https://img.shields.io/badge/docker-ghcr.io-blue)](https://github.com/lindseystead/ai-pdf-autofiller/pkgs/container/ai-pdf-autofiller)

[Try in Codespaces](#try-it-now) · [Install](#install) · [API](#api) · [Recipes](recipes/) · [Docs](docs/)

[![Open in GitHub Codespaces](https://github.com/codespaces/badge.svg)](https://codespaces.new/lindseystead/ai-pdf-autofiller)

**Keywords:** `pdf` · `acroform` · `form-filling` · `fastapi` · `python` · `automation` · `api` · `docker` · `document-processing` · `govtech` · `w9` · `self-hosted`

</div>

---

## What it does

Turn `{"firstname":"Jane","lastname":"Doe"}` into a filled PDF — even when the form uses `txtFName`, `givenName`, or `field_12`.

| Input | Output |
|-------|--------|
| Any fillable AcroForm PDF | Completed PDF with fields written |
| JSON user profile | Mapped automatically via aliases + normalization |
| Optional AI (off by default) | Semantic inference for opaque field names |

**Popular uses:** W-9 / tax forms · HR onboarding packets · government PDFs · insurance intake · workflow automation (n8n, Zapier, curl)

## Playground

Upload a PDF, paste JSON, download the result — no Postman required.

<img src="docs/assets/playground-preview.png" alt="Browser playground — upload PDF, paste JSON, download filled PDF" width="700" />

**Try free:** [Open in GitHub Codespaces](https://codespaces.new/lindseystead/ai-pdf-autofiller) → auto-opens `/playground`

## Try it now

```bash
# Docker (fastest local)
docker run --rm -p 8000:8000 -e API_AUTH_ENABLED=false \
  ghcr.io/lindseystead/ai-pdf-autofiller:latest
# → http://localhost:8000/playground

# Or fill from curl
curl -s -X POST http://localhost:8000/fill \
  -F "pdf_file=@samples/sample_form.pdf;type=application/pdf" \
  -F 'user_data={"firstname":"Jane","lastname":"Doe","dob":"1990-01-01"}' \
  -F "strict=true" -o filled.pdf
```

## Install

| Method | Command |
|--------|---------|
| **Docker** | `docker run -p 8000:8000 -e API_AUTH_ENABLED=false ghcr.io/lindseystead/ai-pdf-autofiller:latest` |
| **GitHub Release** | `curl -fsSL .../scripts/install-from-release.sh \| bash` |
| **From source** | `git clone https://github.com/lindseystead/ai-pdf-autofiller.git && cd ai-pdf-autofiller && pip install -r requirements-dev.txt && make run-api` |

```python
from pdf_autofiller import fill
fill("form.pdf", {"firstname": "Jane", "lastname": "Doe"}, "filled.pdf")
```

## API

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/playground` | Browser UI |
| `GET` | `/health` | Health + dependency checks |
| `POST` | `/fill` | PDF in, filled PDF out |

Full contract: [docs/API.md](docs/API.md)

## Why this exists

Manual PDF field mapping does not scale. AI-only fillers are hard to audit. **PDF Autofiller** is deterministic-first: most fields match via normalization and aliases with **no API key required**.

## Features

- FastAPI HTTP API with structured error codes
- Browser playground at `/playground`
- Python SDK (`fill()` + `PDFAutofillerClient`)
- W-9 and HR alias packs + [recipes](recipes/)
- Docker on GHCR · Render blueprint · GitHub Release wheels
- Auth, rate limits, and upload guards on by default

## Architecture

```mermaid
flowchart LR
    A[PDF + JSON] --> B[pipeline]
    B --> C[pdf_reader]
    C --> D{AI?}
    D -->|optional| E[field_semantics]
    D -->|skip| F[mapping]
    E --> F --> G[pdf_writer] --> H[Filled PDF]
```

[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)

## Recipes

| Recipe | Form |
|--------|------|
| [w9.md](recipes/w9.md) | IRS W-9 |
| [hr-onboarding.md](recipes/hr-onboarding.md) | Employee intake |
| [sample-form.sh](recipes/sample-form.sh) | One-line demo |

## Documentation

| Doc | Contents |
|-----|----------|
| [docs/API.md](docs/API.md) | Endpoints and errors |
| [docs/OPERATIONS.md](docs/OPERATIONS.md) | Config and deployment |
| [docs/TESTING.md](docs/TESTING.md) | Tests and CI |
| [docs/integrations/](docs/integrations/) | n8n, Zapier, LangChain |
| [CONTRIBUTING.md](CONTRIBUTING.md) | How to contribute |
| [CHANGELOG.md](CHANGELOG.md) | Release history |

## Development

```bash
make test && make lint && make smoke-check
```

105 tests · 85%+ coverage · Python 3.11 & 3.12

## License

MIT — [LICENSE](LICENSE)

---

<div align="center">

**Star the repo** if this saves you from mapping `txtFirstName` by hand.

</div>
