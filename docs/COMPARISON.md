# How PDF Autofiller Compares

Honest comparison for teams evaluating PDF form automation.

## vs Manual field mapping

| | Manual maps | PDF Autofiller |
|---|---|---|
| Setup per PDF | Hours of dev time | Minutes (upload + JSON) |
| Maintenance | Breaks when PDF updates | Alias packs + optional AI |
| Auditability | Depends on implementation | Deterministic path is fully traceable |
| Cost | Engineer salary | Free (self-hosted) |

## vs DocuSign / Adobe PDF Services

| | PDF Autofiller | DocuSign API | Adobe PDF Services |
|---|---|---|---|
| Self-host | ✅ | ❌ SaaS only | ❌ SaaS only |
| Per-fill cost | $0 | Per-envelope pricing | Per-transaction pricing |
| Open source | ✅ MIT | ❌ | ❌ |
| Field-name agnostic | ✅ aliases + optional AI | Template-based | Template-based |
| E-signature workflow | ❌ (fill only) | ✅ Full CLM | ✅ Full suite |

**Best for PDF Autofiller:** You already have fillable PDFs and a JSON user profile — you need programmatic filling without per-document SaaS fees.

**Best for DocuSign/Adobe:** You need legally binding signatures, recipient workflows, and enterprise CLM.

## vs AI-only form fillers

| | AI-only | PDF Autofiller |
|---|---|---|
| Deterministic matching | ❌ | ✅ default path |
| Works offline / no API key | ❌ | ✅ |
| LLM cost per form | Every request | Only when enabled |
| Explainable mapping | Hard | `FillReport` + headers |
| Handles unknown fields | Guesses | Flags `requires_review` |

## vs Building it yourself with pypdf

| | DIY pypdf script | PDF Autofiller |
|---|---|---|
| Time to production | Days–weeks | Minutes |
| Key normalization | You build it | Built-in |
| Type coercion | You build it | Built-in |
| Required field enforcement | You build it | Built-in |
| HTTP API + auth + rate limits | You build it | Built-in |
| Test coverage | You write it | 85%+ enforced |

## Positioning statement

> **Stop mapping `txtFirstName` by hand.** PDF Autofiller is the open-source engine that turns any AcroForm PDF + JSON profile into a completed document — deterministic by default, AI when you need it.
