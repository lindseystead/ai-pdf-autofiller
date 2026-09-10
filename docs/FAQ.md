# FAQ

## How is this different from AI-only PDF fillers / SaaS?

PDF Autofiller is **deterministic-first**. Field names are matched via normalization and alias packs (for example `txtFirstName` ↔ `firstname` / `given_name`) with **no API key and no network call**. Optional semantic inference and AI fallback exist for opaque names like `field_12`, but they are **off by default**. `/inspect` marks such names with `name_quality: "opaque"` and returns `mapping_hints`.

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

- Choice (`/Ch`) fields are written when the value matches a declared `/Opt` (case-insensitive). Unmatched options are reported in `skipped_unwritable_fields` with reason `unresolved_choice_option`.
- Signature (`/Sig`) fields are **not** filled — they appear in `skipped_unwritable_fields` / `X-PDF-Fields-Skipped-Unwritable` with reason `signature_field`.
- Missing widgets, unresolved checkbox/radio states, and confirmed write failures are reported the same way (`missing_widget`, `unresolved_button_state`, `write_failed`) — never silent.

## What does `strict` mean?

`strict=true` (default) turns off **AI fallback mapping** only. It does **not** allow incomplete required fields. `/fill` still returns `required_fields_unresolved` when required widgets cannot be mapped or written.

## Dates on the default path

Deterministic enrichment types known date semantics (`date_of_birth`, `start_date`, `signature_date`, `*_date`, …) as `date`. Common US/EU forms like `01/15/1990` are normalized to `YYYY-MM-DD` without AI. Unparseable date strings are flagged `requires_review` and skipped on write (required dates then fail `/fill`).

## Filled values missing in a PDF viewer?

By default `/fill` sets AcroForm `/NeedAppearances` so viewers regenerate visible field glyphs from written `/V` values. If a viewer still shows blanks, try `flatten=true` (burns appearances into page content) or open the file in another viewer. Pass `need_appearances=false` only when you intentionally want the prior appearance streams left as-is.

## More docs

- [API.md](API.md) — HTTP contract  
- [OPERATIONS.md](OPERATIONS.md) — deployment and env vars  
- [integrations/](integrations/) — n8n / Zapier notes  
- [../samples/README.md](../samples/README.md) — fixtures proven in CI  
- [../recipes/](../recipes/) — worked examples against those fixtures  
