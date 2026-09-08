# FAQ

## How is this different from AI-only PDF fillers / SaaS?

PDF Autofiller is **deterministic-first**. Field names are matched via normalization and alias packs (for example `txtFirstName` ↔ `firstname` / `given_name`) with **no API key and no network call**. Optional semantic inference and AI fallback exist for opaque names like `field_12`, but they are **off by default**.

Compared with typical SaaS / AI-only tools:

| | PDF Autofiller | Typical AI-only / SaaS filler |
|--|----------------|-------------------------------|
| Default path | Local aliases + rules | LLM vision / extraction |
| Auditability | Mapping reason + confidence per field | Often opaque |
| Cost | Self-hosted; AI optional | Per-page / subscription |
| Privacy | User values never sent to providers on the default path | Form contents often leave your network |
| Offline | `from pdf_autofiller import fill` works without a server | Usually requires their cloud |

Use this project when you need an auditable, self-hosted fill for AcroForm PDFs. Use a SaaS if you primarily need OCR of **scanned** images with no form fields.

## AcroForm vs scanned PDFs

This tool fills **AcroForm** (and similar interactive) fields — widgets with names like `txtSSN`. It does **not** OCR a flat scanned image into text boxes. If `/inspect` returns `field_count: 0`, the PDF is not fillable as shipped; regenerate it as an AcroForm or use an OCR pipeline first.

## Authentication defaults

- `API_AUTH_ENABLED` defaults to **`true`** (fail closed).
- Set `API_AUTH_TOKEN` in production.
- For local/trusted use only: `API_AUTH_ENABLED=false`.
- Unauthenticated: `GET /`, `/playground`, `/health`, `/version`, `/samples/sample_form.pdf`.
- Protected when auth is enabled: `POST /fill`, `/preview`, `/inspect`.

## Local `fill()` vs HTTP `/fill`

| | Local library | HTTP API |
|--|---------------|----------|
| Import | `from pdf_autofiller import fill` | `PDFAutofillerClient` or curl |
| Server | Not required | FastAPI process |
| Best for | Scripts, CI, offline batch | Playground, n8n/Zapier, multi-language clients |

Local `fill()` and the server `POST /fill` path share `run_fill_pipeline` (same mapping and writer behavior). `PDFAutofillerClient` is an HTTP client that calls the remote `/fill` endpoint.

## Preview before fill

`POST /preview` runs read → enrich → map and returns JSON decisions **without** writing a PDF. Use it in the playground (**Preview Mapping**) or from curl to debug misses before `/fill`.

## Signatures and choice fields

- Choice (`/Ch`) fields are written (value as-is or matched to `/Opt` when present).
- Signature (`/Sig`) fields are **not** filled — digital signature widgets are unsupported.

## More docs

- [API.md](API.md) — HTTP contract  
- [ROADMAP.md](ROADMAP.md) — phased plan  
- [OPERATIONS.md](OPERATIONS.md) — deployment and env vars  
- [integrations/](integrations/) — n8n / Zapier notes  
