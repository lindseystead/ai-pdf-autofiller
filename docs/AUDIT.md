# Document Automation Architecture Audit — PDF Autofiller

**Prepared by:** Lead Principal Software Architect
**Date:** 2026-05-31
**Audit type:** Final consolidated synthesis of four independent specialist read-only audits (Architecture, Document Engineering, Security & Compliance, Business Strategy)

---

> **Remediation status.** Several findings from this audit have since been
> addressed and are no longer open:
>
> _v0.2.0_
> - **Boolean → checkbox/radio write defect** (Sections 2, 3, 12 item #2): `/Btn`
>   values are now translated to valid PDF state names in `pdf_writer.py`, so
>   boolean-style inputs toggle the control. Covered by new tests.
> - **`requires_review` silently lossy** (Section 6): `fill_pdf` now returns a
>   `FillReport`, and `POST /fill` surfaces dropped fields via the
>   `X-PDF-Fields-Skipped-Review` / `X-PDF-Fields-Skipped-Empty` headers.
>
> _v0.3.0 (security pass)_
> - **9.1 PII egress (HIGH):** raw user values and field current values are no
>   longer sent to the provider — only key names and value type names.
> - **9.2 Default-open `/fill` (MED):** auth now defaults on and fails closed;
>   per-client rate limiting added (`rate_limited`).
> - **9.3 Decompression-bomb / DoS (MED):** page-count cap (`pdf_too_many_pages`)
>   and an extraction time budget (`pdf_processing_timeout`); extraction runs off
>   the event loop. Residual risk: a single-page high-ratio stream within the
>   5 MiB cap is bounded but not fully eliminated — keep memory limits at the
>   container level.
> - **9.5 Temp-file cleanup (MED):** consolidated into a single guard that runs
>   on every non-success path, including timeouts and cancellations.
> - **9.6 Audit trail (MED):** a structured, PII-free audit line is now emitted
>   per fill. Durable storage/retention remains a deployment responsibility.
> - **Dependencies:** `pypdf` and `python-multipart` (both parse untrusted input)
>   pinned to patched, CVE-fixed minimums; total extracted text is now bounded.
>
> Still open (feature/scale, not request-path safety): template persistence,
> async/bulk, multi-tenancy/RBAC, signatures, OCR, and a durable audit-log
> *store* — each tracked as a GitHub issue. The only request-path residual is the
> single-page decompression edge noted under 9.3 (bounded by the upload cap +
> container memory limits). The `starlette` PYSEC-2026-161 advisory is resolved:
> FastAPI was bumped to >= 0.136 and starlette pinned >= 1.0.1.

---

## Headline Verdict

**This is a well-engineered, deterministic-first AcroForm-fill engine-core — a clean, auditable microservice. It is NOT yet a platform. But it is a credible foundation for one.**

The codebase (~1,578 LOC of source across 6 lean modules) does one thing genuinely well: it extracts AcroForm fields from a single uploaded PDF, maps caller-supplied data to those fields using an auditable deterministic-first pipeline with optional LLM assistance, enforces required-field completion, and streams the filled PDF back — statelessly. Module boundaries are crisp, error contracts are machine-readable, test coverage has an 85% floor, and optional features (semantic inference, fallback mapping) degrade gracefully.

What it is *not*: there is no template registry, no persistence, no workflow engine, no approval UI, no multi-tenancy, no checkbox/signature writing, no bulk/async processing, and no front-end. The much-claimed "template system" does not exist — **the uploaded PDF *is* the template, ephemerally, per request.**

The strategic read: this is the highest-leverage **white-label / OEM engine core** the auditors evaluated, three to six weeks of hardening away from being a sellable building block — and a defensible foundation for a vertical SaaS (municipal or engineering forms) if a domain co-founder is found.

---

## SECTION 1 — Architecture Overview

### 1.1 System Scope & Boundaries

A **stateless, single-endpoint HTTP service** for deterministic-first PDF form filling.

**In scope:** Extraction-only PDF reading → optional semantic inference (LLM-backed, opt-in) → deterministic field mapping → optional controlled LLM fallback mapping → required-field enforcement → stream filled PDF back.

**Explicitly out of scope** (confirmed by all four auditors): frontend/UI, persistent storage/database, audit-log store, template registry, deployment orchestration (Kubernetes/Helm), bulk/async endpoints, job queues, webhooks, and OCR/scanned-document handling (AcroForm-only).

### 1.2 Module Inventory (~1,578 LOC source)

| Module | LOC | Single Responsibility |
|--------|-----|------------------------|
| `models.py` | 99 | Pydantic v2 data contracts only — no logic |
| `pdf_reader.py` | 239 | Extraction only (metadata, form fields, text regions); no inference |
| `field_semantics.py` | 249 | OpenAI client wrapper; semantic inference with graceful degradation |
| `mapping.py` | 388 | Deterministic-first data mapping + optional LLM fallback |
| `pdf_writer.py` | 233 | PDF writing + required-field enforcement |
| `api_service.py` | 362 | HTTP boundary, auth, request lifecycle, temp-file cleanup, error contracts |

Dependency chain: `pypdf` (extract/write) → `pydantic` (contracts) → `openai` (optional semantics) → `fastapi` (HTTP). Tests: ~1,348–1,350 LOC across 5 files.

### 1.3 ASCII Architecture Diagram (the REAL system)

```
┌──────────────────────────────────────────────────────────────────────┐
│  CLIENT — POST /fill  (multipart)                                      │
│  pdf_file (binary) · user_data (JSON) · flags: strict,                 │
│  allow_fallback_mapping, use_semantic_inference                        │
└───────────────────────────────┬──────────────────────────────────────┘
                                │
                                ▼
┌──────────────────────────────────────────────────────────────────────┐
│  FASTAPI BOUNDARY            api_service.py:229–310                     │
│  • Optional API-key auth (secrets.compare_digest)  :193–212            │
│  • MIME check :254–259 · JSON parse :261–267                           │
│  • Size <5MB + "%PDF-" signature :269–290                              │
│  • Write to per-request tempfile.TemporaryDirectory :269               │
│  • Request-ID middleware + timing :173–190                             │
└───────────────────────────────┬──────────────────────────────────────┘
                                ▼
┌──────────────────────────────────────────────────────────────────────┐
│  PDF EXTRACTION             pdf_reader.py:200–239                       │
│  read_pdf() → DocumentStructure                                        │
│   ├─ _extract_form_fields() :110–173                                   │
│   │    get_fields() [AcroForm]  OR  widget-annotation fallback         │
│   │    type /Tx /Btn /Ch /Sig :26 · value :46 · required /Ff 0x02 :71  │
│   │    page via /P reference :125                                      │
│   └─ _extract_text_regions() :176–197  (page text → semantic context)  │
│  NO inference here.                                                    │
└───────────────────────────────┬──────────────────────────────────────┘
                                ▼
┌──────────────────────────────────────────────────────────────────────┐
│  OPTIONAL SEMANTIC ENRICHMENT   api_service.py:293–297 +               │
│                                 field_semantics.py                      │
│  IF use_semantic_inference=True AND MODEL_PROVIDER_API_KEY set:        │
│    infer_field_semantics() → gpt-4o-mini (json_object) :72–122         │
│    → FieldSemantics(meaning, expected_type, confidence)               │
│  ELSE / on failure:                                                    │
│    _fallback_semantics() — deterministic, confidence=0.5  :92–106      │
│  → EnrichedFormField[]                                                 │
└───────────────────────────────┬──────────────────────────────────────┘
                                ▼
┌──────────────────────────────────────────────────────────────────────┐
│  DETERMINISTIC MAPPING        mapping.py:274–388                        │
│  PASS 1 (always, auditable):                                          │
│   find_deterministic_match() :118–164                                  │
│    ├─ normalize_key() snake_case :35–54                                │
│    ├─ direct match → conf 0.95 (0.70 if review)                        │
│    ├─ FIELD_ALIASES (only 5 concepts) :26–32 → 0.90 (0.65 if review)   │
│    └─ coerce_value() str/date/number/bool :57–115                      │
│  PASS 2 (only if NOT strict AND allow_fallback_mapping):              │
│   semantic_fallback_mapping() high-value fields only → gpt-4o-mini     │
│   :167–271  (no-op if client unavailable)                             │
│  → MappingResult{decisions[], missing_required[], unmapped_user_keys[]}│
└───────────────────────────────┬──────────────────────────────────────┘
                                ▼
┌──────────────────────────────────────────────────────────────────────┐
│  PDF WRITE + ENFORCEMENT       pdf_writer.py:87–215                     │
│  clone_reader_document_root() (preserve formatting) :134               │
│  _collect_pdf_fields() :38–84                                          │
│  skip if requires_review (required→track) :147–153 · skip if None      │
│  update_page_form_field_values() batch, per-field fallback :171–185    │
│  REQUIRED-FIELD VALIDATION :187–210                                    │
│    → raise UnresolvedRequiredFieldsError if any unresolved :18–35,206  │
│  writer.write(output) :213–215                                        │
└───────────────────────────────┬──────────────────────────────────────┘
                                ▼
┌──────────────────────────────────────────────────────────────────────┐
│  RESPONSE                     api_service.py:306–310                    │
│  FileResponse(application/pdf) + BackgroundTask(temp_dir.cleanup)      │
│  OR _api_error(){code,message,details} on any failure :63–89           │
└──────────────────────────────────────────────────────────────────────┘

TEMP LIFECYCLE: create :269 → write input :290 → read :220 →
   write output :215 → stream → BackgroundTask cleanup AFTER response.
STATELESS: no DB, no cache, no session; context discarded per request.
```

### 1.4 Layer Presence

| Layer | Status | Evidence |
|-------|--------|----------|
| HTTP API boundary | Present | `api_service.py:146–152`; /fill, /health, /version |
| Request validation | Present | MIME, JSON, signature, size — `api_service.py:254–289` |
| Authentication | Present (opt-in, default OFF) | X-API-Key, `secrets.compare_digest` — `api_service.py:193–212` |
| PDF reader (AcroForm) | Present | `pdf_reader.py:110–173` |
| PDF writer | Present | `pdf_writer.py:87–215` |
| Semantic inference | Present (opt-in) | `field_semantics.py:41–122` |
| Deterministic mapping | Present (always) | `mapping.py:35–164` |
| LLM fallback mapping | Present (opt-in) | `mapping.py:167–271` |
| Required-field enforcement | Present | `pdf_writer.py:206–210` |
| Temp-file lifecycle | Present | `api_service.py:269,310` |
| Logging/observability | Present (ephemeral) | `api_service.py:173–190` |
| OCR / scanned PDFs | **Absent** | Out of scope (README) |
| Frontend / DB / templates / async / bulk | **Absent** | Confirmed by all auditors |

**Production-readiness gaps (architecture auditor):** no API versioning (model `gpt-4o-mini` hardcoded at `field_semantics.py:98`), no rate limiting, no explicit timeout on LLM calls.

---

## SECTION 2 — Document Engine Analysis

The document engine is **extraction-only and template-agnostic**: the uploaded PDF defines the form on-the-fly. Fields are read via `PdfReader.get_fields()` with a widget-annotation fallback (`pdf_reader.py:110–173`). Mapping is deterministic-first (Section 4). Writing clones the source to preserve formatting and uses `update_page_form_field_values()` with per-field fallback.

**Value coercion** (`coerce_value()`, `mapping.py:57–115`): string (pass-through), date (**ISO `YYYY-MM-DD` only** — other formats flagged `requires_review`), number (float/int), boolean. **Confirmed defect (both engine and security auditors):** booleans coerce to the *string* `"true"`/`"false"` (`mapping.py:108`), which will not toggle an AcroForm checkbox that expects `/Yes`/`/Off` or integer state — a silent data mismatch.

### 10 / 100 / 1000 Forms Verdict

| Horizon | Verdict | First thing that breaks |
|---------|---------|--------------------------|
| **10 templates** | Feasible (~1 week tuning) | Text-only forms covered; each new convention re-tunes `FIELD_ALIASES`. |
| **100 templates** | Breaks at ~20–30 | `FIELD_ALIASES` explosion (5 → 50–75 entries, hand-maintained); no template persistence means no learned mappings carry over; LLM fallback becomes the default path. |
| **1,000 templates** | Not feasible without major refactor | Code deploy per form type; alias collision destroys determinism; fallback API volume/cost/latency balloon; checkbox/signature gaps block 20–50% of forms. |

---

## SECTION 3 — Template System

**There is no template system.** No registry, no storage, no per-template alias packs, no persisted mappings. This is the single largest gap between any "platform" framing and reality, and all four auditors independently confirmed it.

**AcroForm field-type support:**

| Type | Detect | Write | Notes |
|------|--------|-------|-------|
| `/Tx` text | Yes | Yes | Fully functional (string values) |
| `/Btn` checkbox/radio | Yes | **Broken** | Boolean→string `"true"`/`"false"`; PDF on/off state not handled |
| `/Ch` choice/dropdown | Yes | Partial | Raw string write; no option-list validation |
| `/Sig` signature | Yes (detect only) | **No** | No signing, no visual placement |

**Not supported:** coordinate/positional mapping, image insertion, repeating sections / multi-row tables, calculated/formula fields, field composition (e.g., full-name → first+last).

---

## SECTION 4 — Data Mapping Engine

**Current design — deterministic-first, auditable, but brittle at scale.** Every field flows through `normalize_key()` → `find_deterministic_match()` → `coerce_value()`, with explicit confidence scores (0.95 direct, 0.90 alias, 0.70/0.65 under coercion ambiguity, 0.0 none) and a `requires_review` flag rather than silent coercion. Optional LLM fallback (`semantic_fallback_mapping()`) runs only for high-value unmapped fields (required OR confidence > 0.8) when `not strict and allow_fallback_mapping`.

**Structural limits:** only 5 hardcoded semantic concepts (`FIELD_ALIASES`, `mapping.py:26–32`); one-user-key→one-field (no composition/derivation); ISO-only dates with no locale support; the boolean→string defect; and no external config or learned-mapping store — so alias maintenance grows O(templates × fields).

### Recommended Scalable Mapping Architecture

1. **Externalize `FIELD_ALIASES`** into a config/DB registry keyed by document type (lift out of `mapping.py:26–32`).
2. **Per-template field metadata**: expected types, option lists, checkbox on/off values, date formats — `DocumentMetadata` (`models.py:32–40`) currently carries no field-level metadata.
3. **Type-aware plugin coercers** (`TextHandler`, `DateHandler`, `CheckboxStateHandler`, `ChoiceHandler`) replacing the monolithic `coerce_value()`; fixes the boolean defect.
4. **Learned-mapping store**: persist `(form_hash, user_key → pdf_field)` and look up before deterministic/fallback, cutting LLM calls and latency.
5. **Per-template transform pipeline**: semantic inference → deterministic → template aliases → typed coercion → validation.

---

## SECTION 5 — Document Automation Capability (8 doc types)

No category is fully supported today; text-only forms work, but checkboxes, signatures, and composition block real-world completion.

| Doc Type | Supported | Partial | Not Supported | Blocker |
|----------|:---------:|:-------:|:-------------:|---------|
| Government (W-4, 1040, DMV) | | ✓ | | Checkbox state broken; date-format ambiguity |
| Permit applications | | ✓ | | Checkboxes don't toggle; signatures unwritable; unvalidated dropdowns |
| Engineering / technical | | ✓ | | No calculated fields, no multi-select; text/numeric OK if ISO |
| Grant applications | | ✓ | | No repeating sections ("list up to 10 projects") |
| Intake (medical/legal/HR) | | ✓ | | Checkbox bug + no signatures (critical for compliance) |
| Insurance | | ✓ | | Checkbox state + exact-value/dropdown validation missing |
| HR onboarding | | ✓ | | No repeating employment history; no conditional logic |
| Legal / contract | | ✓ | | Signatures absent; no calculated/conditional text |

**Verdict: 0 fully supported, 8 partial, ≥1 hard blocker each.** The engine handles text-field forms well and fails the moment checkboxes, signatures, or field composition are required.

---

## SECTION 6 — Workflow Automation

**Workflow automation is effectively absent.** The service is stateless and single-request: no approval queue, no notifications, no webhooks, no async/batch, no persistent decision trail.

The most consequential finding here, raised by the security/workflow auditor, is that **the `requires_review` mechanism is half-built and silently lossy**: decisions flagged `requires_review=true` are *excluded* from the written PDF (`pdf_writer.py:147–153`) but there is **no UI, queue, or notification** to surface them. For non-required fields the caller receives a 200-OK PDF with those fields silently blank — *data loss masquerading as success*. For required fields, `UnresolvedRequiredFieldsError` fires (`pdf_writer.py:206–210`) but the error does not give a human a way to inspect and approve the flagged mappings.

Lifecycle mapping: Intake (manual) · Semantic analysis (optional, auto, no gate) · Deterministic mapping (auto) · Fallback mapping (optional, auto, no gate) · **Approval/review — ABSENT** · Generation (auto) · **Notification — ABSENT** · **Audit trail — logging only, ephemeral.**

**Remediation path (phased):** (1) make `requires_review` actionable — persist `FieldMappingDecision`s, add `GET /fill/{id}/decisions` and `POST /fill/{id}/approve`, write only approved decisions; (2) approval dashboard; (3) Slack/email notifications + escalation; (4) persistent audit log.

---

## SECTION 7 — Business Potential

Six product models, scored from the current codebase (effort = net-new work on top of what exists).

| # | Model | Market Fit | Effort | Yr-1 Rev | Yr-3 Rev | Moat | Verdict |
|---|-------|-----------|--------|----------|----------|------|---------|
| 1 | PDF Autofill Tool (SDK/narrow SaaS) | Low | 2–4 wk | $5–20k | $20–50k | None | **Skip** — commoditized by free pypdf wrappers |
| 2 | Horizontal Document-Automation SaaS | Moderate | 12–16 wk | $10–50k | $200–500k | Low | Only with a front-end co-founder; crowded (Adobe, Zapier, HubSpot) |
| 3 | Municipal Forms Platform (vertical) | **Strong** | 20–24 wk | $20–100k | $500k–$1M+ | **High** | **Yes** with gov domain expertise; procurement friction = moat |
| 4 | Engineering Forms Automation (vertical) | **Strong** | 10–14 wk | $50–150k | $400k–$1M+ | **High** | **Yes** with manufacturing/PLM background |
| 5 | Grant / Nonprofit Automation | Mod–High | 10–12 wk | $10–50k | $150–300k | Moderate | Viable lifestyle business; price-sensitive, slow GTM |
| 6 | White-label / OEM Engine | High | **4–6 wk** | $20–100k | $200k–$2M+ | Moderate | **Best fit for THIS codebase** — logic already abstracted & tested |

**Strategic read:** the codebase's deterministic, auditable, well-tested core is most valuable as an **embeddable engine** (model 6) — lowest effort, highest leverage, no front-end required — with **engineering or municipal vertical SaaS** as the higher-ceiling second act if a domain co-founder is found. Partner concentration is the main risk for the OEM path.

---

## SECTION 8 — Scalability (what breaks first)

In failure order as the system scales:

1. **`FIELD_ALIASES` dictionary explosion (~20–30 templates).** Hand-maintained 5-concept dict (`mapping.py:26–32`); every new naming convention needs a code change + deploy.
2. **No template persistence / learned mappings.** `map_user_data_to_fields()` is stateless (`mapping.py:274–388`); knowledge from form A never benefits form B.
3. **LLM-fallback overflow.** As deterministic recall drops, fallback becomes the default path → API cost, latency, and rate-limit exposure climb.
4. **Field-type gaps (checkbox/signature).** 20–50% of real forms blocked.
5. **No async/bulk.** One PDF per synchronous request; 1,000 fills = 1,000 sequential calls (`tempfile.TemporaryDirectory` per request, no job store).
6. **Operational gaps.** No rate limiting, no LLM timeout, no PDF decompression-bomb guard (Section 9) — each a throughput/availability ceiling under load.

**The stateless design is a genuine strength for horizontal scaling of the *fill* operation** — but it is exactly what prevents scaling across *template variety*. The first wall is alias maintenance, not compute.

---

## SECTION 9 — Security & Compliance

| # | Finding | Severity | File:Line | Remediation |
|---|---------|:--------:|-----------|-------------|
| 9.1 | **PII egress to external LLM** — field metadata, ≤500-char surrounding page text, and ≤50-char user-data value samples sent to gpt-4o-mini (no consent gate, no DPA enforcement). GDPR/PIPEDA/HIPAA exposure. | **HIGH** | `field_semantics.py:72–175`; `mapping.py:204–235` | Mask values (send keys + types only); strip page-text content to labels; default both LLM flags OFF; require documented DPA before enabling. |
| 9.2 | **Default-open `/fill`** — `API_AUTH_ENABLED` defaults `false`; no RBAC, no rate limiting. | MEDIUM | `api_service.py:33` | Default auth ON; add per-IP/key rate limiting (middleware hook `:173`); per-request LLM cost tracking. |
| 9.3 | **PDF decompression-bomb / DoS** — size + magic-byte checks only; no expansion-ratio guard, no read timeout. | MEDIUM | `api_service.py:276–290`; `pdf_reader.py:200` | Reject high compression-ratio uploads; wrap `read_pdf()` in a timeout; set container memory limit. |
| 9.4 | **Obfuscated SDK import** — `getattr(provider_sdk, "".join(["Open","A","I"]))` defeats SAST/grep for OpenAI usage. (Architecture auditor flagged it as unclear "security theater"; security auditor as a supply-chain/audit red flag — both agree: remove it.) | LOW | `field_semantics.py:62` | Import `OpenAI` directly; add CI lint banning string-built SDK imports. |
| 9.5 | **Temp-file cleanup depends on BackgroundTask** — if the task is cancelled (client disconnect, worker crash) PII-laden PDFs persist in `/tmp`. | MEDIUM | `api_service.py:310,346` | Use `with TemporaryDirectory()` context manager; add `finally` cleanup; document a `/tmp` sweep cron. |
| 9.6 | **No persistent audit trail** — only request-ID/method/path/status/duration logged; field decisions discarded. GDPR Art. 5(f), HIPAA §164.312(b), PCI 10.2 gaps. | MEDIUM | `api_service.py:182–189` | Structured per-decision logging; forward to central store; optional `mapping_summary` in response. |
| 9.7 | **Coercion ambiguity unexplained** — ISO-only dates / ambiguous booleans flagged `requires_review` with no reason returned to caller. | LOW–MED | `mapping.py:57–116`; `models.py:74–82` | Add `coercion_notes` field; surface reasons in 422 detail. |

**Correctly compliant:** no encryption-at-rest concern — nothing is persisted by the application; temp PDFs are plaintext by design (caller's responsibility), and TLS/network isolation are correctly delegated to the deployment environment.

---

## SECTION 10 — Feature Completeness Matrix

| Feature | Present | Partial | Missing | Risk |
|---------|:-------:|:-------:|:-------:|------|
| Field mapping | ✓ | | | Low (auditable) but only 5 aliases — recall ceiling |
| Validation | | ✓ | | Required-field enforcement strong; coercion brittle (ISO dates, bool defect), reasons not surfaced |
| PDF generation | | ✓ | | Text solid; checkbox/radio/signature broken or absent |
| Template management | | | ✓ | **High** — no registry; blocks scale past ~20–30 forms |
| Document versioning | | | ✓ | High for regulated/vertical use |
| Signatures | | ✓ | | Detected only, never written — hard blocker for legal/contract |
| Image support | | | ✓ | Medium — no image insertion |
| Bulk generation | | | ✓ | High — no async/batch/queue |
| Workflow support | | ✓ | | **High** — `requires_review` silently lossy; no approval/notify |
| API support | ✓ | | | Versioning, rate-limit, LLM timeout missing |
| Audit logs | | ✓ | | **High** — ephemeral only; compliance gap |

---

## SECTION 11 — What Is This Really? (CTO take)

**Name it:** a **high-quality, deterministic-first PDF AcroForm-fill microservice / engine-core.** Not a platform, not a product, not yet a company.

**Strongest part:** the deterministic-first, auditable mapping pipeline (`mapping.py:118–164`) — explicit confidence scores, ambiguity flagged not hidden, required-field enforcement that refuses to emit an incomplete PDF (`pdf_writer.py:206–210`), graceful degradation when no API key is present, clean single-responsibility modules, and rigorous tests (85% floor). This is production-grade discipline rarely seen in form-fill tooling and earns trust in regulated domains.

**Weakest part:** no template/persistence layer — every request starts from scratch, nothing is learned or reused. Closely tied: the tiny 5-concept alias set, text-only writing (checkbox/radio/signature broken or absent, ~20–30% of real PDFs), no multi-tenancy, and no workflow/batch.

**Biggest opportunity:** add a light template + audit persistence layer and checkbox/radio writing, then **white-label the engine to 3–5 enterprise partners** (DocuSign, Zapier, Formstack, SAP, monday.com). ~6–10 weeks of work; the codebase's transparency-and-audit strength is exactly what enterprise partners need to expose to their own customers.

**What to build next (in order):** (1) template storage + mapping reuse; (2) checkbox/radio/dropdown writing; (3) audit-log/decision history; (4) webhook + async queue; (5) white-label SDK packaging. Then pursue the engineering or municipal vertical if a domain co-founder appears.

---

## SECTION 12 — Prioritized Roadmap (Top 10)

Scores 1–5 (5 = highest). Effort in weeks.

| Rank | Improvement | Impact | Effort | Revenue | Arch. Value | Why here |
|:----:|-------------|:------:|:------:|:-------:|:-----------:|----------|
| 1 | **Template storage + mapping reuse** (PostgreSQL: form_hash, metadata, decisions) | 4 | 2 wk | 3 | 4 | Highest quick ROI; cuts LLM calls; prerequisite for every scaling story |
| 2 | **Checkbox/radio/dropdown write support** (fixes bool→string defect; `/Btn` `/Ch` `/Opt` `/AS`) | 4 | 2–3 wk | 3 | 3 | Lifts coverage ~70%→~90%; unblocks insurance/healthcare/legal |
| 3 | **Webhook + async job queue** (Celery/RQ; `POST /fill`→job_id, callback) | 4 | 3 wk | 4 | 4 | Unlocks bulk/B2B + white-label distribution |
| 4 | **Audit log + decision history** (immutable table; who/what/when/why) | 3 | 1 wk | 3 | 4 | Low effort, compliance moat; gates vertical SaaS |
| 5 | **White-label SDK packaging** (Python/Node/Go; retries, rate-limit backoff) | 3 | 2 wk | 4 | 3 | Essential for the OEM revenue model |
| 6 | **Multi-tenant / org / soft RBAC** (users, orgs, scoped keys, isolation) | 4 | 4 wk | 4 | 5 | Gates SaaS monetization; biggest architectural uplift |
| 7 | **OCR / scanned-PDF support** (Tesseract + layout analysis) | 4 | 4–5 wk | 4 | 2 | Doubles addressable forms; high effort, variable accuracy |
| 8 | **E-signature integration** (DocuSign/HelloSign) | 3 | 2 wk | 3 | 2 | Closes the legal/contract blocker; mostly external calls |
| 9 | **Semantic alias learning** (crowdsource field→concept; grow `FIELD_ALIASES`) | 3 | 2 wk | 2 | 3 | Self-improving recall; reduces LLM fallback over time |
| 10 | **Performance profiling + LLM/prompt caching** (Redis) | 2 | 2 wk | 2 | 3 | Cost/latency hygiene; not urgent |

**Sequencing:** Ship 1–3 first (quick ROI + B2B unlock), then 4–6 (compliance, distribution, SaaS gate), then 7–10 as market direction dictates.

> Cross-auditor note: items 1–2 also directly remediate Section 8's top scalability walls and Section 2's boolean defect; item 4 remediates Section 9.6; the security auditor's "make `requires_review` actionable" work (Section 6) is a prerequisite that rides alongside items 1 and 4.

---

# FINAL OUTPUT

### (1) Architecture Diagram

```
CLIENT ──POST /fill (pdf + user_data + flags)──▶ FASTAPI BOUNDARY
   auth(opt) · MIME/JSON/size/%PDF- · temp dir · request-ID
        │
        ▼  pdf_reader.py        EXTRACTION (AcroForm get_fields / widget fallback;
        │                       type, value, required /Ff 0x02, page, text regions)
        ▼  field_semantics.py   OPTIONAL SEMANTIC ENRICHMENT (gpt-4o-mini, opt-in;
        │                       else deterministic _fallback_semantics conf=0.5)
        ▼  mapping.py           DETERMINISTIC MAP (normalize→direct 0.95 / alias 0.90
        │                       [5 concepts] → coerce) + OPTIONAL LLM FALLBACK
        ▼  pdf_writer.py        WRITE (clone → update_page_form_field_values) +
        │                       REQUIRED-FIELD ENFORCEMENT (raise if unresolved)
        ▼  api_service.py       FileResponse(pdf) + BackgroundTask cleanup  /  _api_error
   STATELESS · NO DB · NO TEMPLATE STORE · NO QUEUE · per-request temp dir deleted
```

### (2) Product Classification

A **deterministic-first PDF AcroForm-fill engine-core / microservice** — well-engineered, auditable, stateless. **Not a platform, not a product, not yet a company.** The claimed "template system" does not exist (uploaded PDF = ephemeral template).

### (3) Scalability Assessment

**10 forms:** feasible (~1 wk tuning). **100 forms:** breaks at ~20–30 (alias-dict explosion, no persistence). **1,000 forms:** not feasible without major refactor (per-form code deploys, alias collisions, LLM-fallback cost/latency overflow, field-type gaps). Statelessness scales the *fill op* horizontally but is precisely what blocks scaling across *template variety*. **First wall: `FIELD_ALIASES` maintenance — not compute.**

### (4) Security Assessment

One **HIGH** (PII egress to OpenAI, no consent/DPA gate); four **MEDIUM** (default-open endpoint, PDF decompression-bomb/DoS, BackgroundTask-dependent temp cleanup, no persistent audit trail); two **LOW/LOW-MED** (obfuscated SDK import, unexplained coercion ambiguity). No encryption-at-rest concern (nothing persisted). **Top fixes:** default LLM flags OFF + value masking; default auth ON + rate limiting; decompression guard + read timeout; context-manager temp cleanup.

### (5) Business Opportunity Assessment

**Best fit for this codebase: White-label / OEM engine** (4–6 wk, $200k–$2M+ Yr-3, moderate moat) — the abstracted, tested core is its strongest asset and needs no front-end. **Higher-ceiling second act: Engineering or Municipal vertical SaaS** (10–24 wk, $500k–$1M+ Yr-3, high moat) if a domain co-founder is found. **Skip** the narrow PDF-autofill tool (commoditized). Horizontal SaaS only with a front-end co-founder.

### (6) Top-10 Roadmap Recap

1. Template storage + mapping reuse · 2. Checkbox/radio/dropdown write (fixes bool defect) · 3. Webhook + async queue · 4. Audit log + decision history · 5. White-label SDKs · 6. Multi-tenant + RBAC · 7. OCR/scanned PDFs · 8. E-signature · 9. Semantic alias learning · 10. Performance + LLM caching. **Ship 1–3 first.**

### (7) What This System Could Become

Today it is a disciplined AcroForm-fill engine-core. With ~6–10 weeks of focused work — template + audit persistence, checkbox/signature writing, async processing, and SDK packaging — it becomes a **credible embeddable document-automation engine** that enterprise partners can resell with confidence, precisely because its deterministic, auditable design is the kind of transparency they must expose to their own regulated customers. With a domain co-founder layered on top (engineering or municipal forms) and the security/compliance gaps closed, it can mature from engine-core into a **defensible vertical document-automation platform**. The foundation is real and well-built; the platform is not yet here — but the distance to it is measured in weeks of well-scoped work, not a rewrite.