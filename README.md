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

[Try in Codespaces](#try-it-now) · [Install](#install) · [CLI](docs/CLI.md) · [API](#api) · [Recipes](recipes/) · [Docs](docs/)

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
# Command line — no server needed
pip install pdf-autofiller

# 1. Get a data file with the keys this form actually wants
pdf-autofiller init form.pdf > me.json

# 2. Check what would happen (writes nothing)
pdf-autofiller inspect form.pdf --data me.json

# 3. Fill it
pdf-autofiller fill form.pdf --data me.json --out filled.pdf --flatten
```

Already have a form someone filled in by hand? Read it back out and keep it:

```bash
pdf-autofiller extract completed.pdf --save-profile jane
pdf-autofiller fill next-form.pdf --profile jane
```

`inspect` is the one to start with on an unfamiliar form: it lists every field,
what the tool thinks each one means, and exactly which of them your data would
fill — before you commit to a fill.

```
 + txtFirstName  text  first_name [required] -> 'Jane'
 ! txtLastName   text  last_name [required]
   txtEmail      text  email_address

would write 1, would skip 1
missing required: txtLastName
legend: + will fill   ? needs review   ! required and unmapped
```

```bash
# Docker (fastest local server)
docker run --rm -p 8000:8000 -e API_AUTH_ENABLED=false \
  ghcr.io/lindseystead/ai-pdf-autofiller:latest
# → http://localhost:8000/playground

# Or fill from curl
curl -s -X POST http://localhost:8000/v1/fill \
  -F "pdf_file=@samples/sample_form.pdf;type=application/pdf" \
  -F 'user_data={"firstname":"Jane","lastname":"Doe","dob":"1990-01-01"}' \
  -F "strict=true" -o filled.pdf
```

## Daily use

The same form, over and over, is the normal case. Save the data once and the
mapping once, then stop repeating yourself:

```bash
pdf-autofiller profile set me --data me.json          # reusable data
pdf-autofiller template save w9 w9.pdf --flatten      # remembered mapping
pdf-autofiller fill w9.pdf --profile me --template w9

# One form, many people — straight from a spreadsheet
pdf-autofiller batch onboarding.pdf --csv staff.csv --out-dir ./packets
```

Nested profiles work as you would expect — `{"contact": {"email": "..."}}`
fills an email field without any flattening on your side.

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
| `GET` | `/v1/health` | Health + dependency checks |
| `POST` | `/v1/inspect` | Fields and a dry-run mapping — writes nothing |
| `POST` | `/v1/fill` | PDF in, filled PDF out |
| `GET`/`PUT`/`DELETE` | `/v1/templates/{name}` | Remembered per-form mappings |
| `GET`/`PUT`/`DELETE` | `/v1/profiles/{name}` | Reusable data sets |

Unversioned paths (`/fill`, `/health`) still work as aliases.
Full contract: [docs/API.md](docs/API.md)

## Why this exists

Manual PDF field mapping does not scale. AI-only fillers are hard to audit. **PDF Autofiller** is deterministic-first: most fields match via normalization and aliases with **no API key required**.

## Features

- CLI (`init`, `inspect`, `fill`, `extract`, `validate`, `batch`, `profile`, `template`) — no server required
- FastAPI HTTP API with structured error codes, versioned under `/v1`
- Dry-run inspection so you can see a mapping before producing a document
- Read values back out of a filled PDF and reuse them as a profile
- Templates and profiles so recurring work is referenced, not repeated
- Batch filling from CSV or JSON; one bad row does not sink the run
- Nested JSON input, explicit per-field overrides, and optional flattening
- Browser playground at `/playground`
- Python SDK (`fill()`, `inspect()`, `PDFAutofillerClient`)
- W-9 and HR alias packs + [recipes](recipes/)
- Docker on GHCR · Render blueprint · GitHub Release wheels
- Token auth, rate limits, and payload bounds on by default
- Untrusted PDFs parsed in a killable subprocess under a wall-clock budget

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
| [docs/CLI.md](docs/CLI.md) | Command line reference |
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

202 tests · 85%+ coverage · Python 3.11 & 3.12

## License

MIT — [LICENSE](LICENSE)

---

<div align="center">

**Star the repo** if this saves you from mapping `txtFirstName` by hand.

</div>
