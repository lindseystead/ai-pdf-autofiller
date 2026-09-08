# Adoption & Best-Practices Roadmap

This roadmap turns PDF Autofiller from a working beta into something people can **find**, **trust**, and **use in production**. It is grounded in:

- End-to-end testing of the current app (see PR notes / CHANGELOG)
- Senior code audit of `src/`, API, playground, CI, and docs
- Industry practice for OSS discoverability, FastAPI production services, and pypdf AcroForm filling

## Goals

1. **Findable** — GitHub/PyPI search and README convert strangers in &lt;30 seconds  
2. **Valuable** — Real forms fill correctly without AI; failures are diagnosable  
3. **Trusted** — CI green, security defaults honest, docs match code  
4. **Usable** — One-command try path; inspect → map → fill loop  
5. **Maintainable** — Lint/type/test gates stable; every feature follows the same patterns  

## Current state (baseline)

| Area | Status |
|------|--------|
| Core fill pipeline | Works on sample AcroForm; deterministic + optional AI |
| Alias packs | Fixed synonym-cluster matching (required for no-AI value) |
| Auth / upload guards | Solid defaults |
| Tests | 100+ tests, ≥85% coverage; corpus hit-rate gate |
| CI lint | Pinned Ruff `0.16.6`; lockfile + docker health smoke |
| PyPI | Requires Release + `PYPI_API_TOKEN` (documented honestly) |
| SDK story | Local `fill()` + HTTP `PDFAutofillerClient` |
| Inspect / preview | `POST /inspect` + `POST /preview` + playground actions |
| Real-form proof | Synthetic sample + HR intake corpus fixtures in CI |
| Discoverability | FAQ, ROADMAP, Pages links, recipes updated |

## Principles (non-negotiable)

- **Deterministic-first** — AI is opt-in; default path must be auditable  
- **Docs = code** — every documented response field exists; every example runs  
- **Fail closed** — auth, size, page, and timeout guards stay on by default  
- **One formatter/linter pin** — CI and local use the same tool versions  
- **Local library works offline** — HTTP API is a deployment option, not a requirement  
- **pypdf form best practice** — `auto_regenerate=False` on writes; optional `flatten` flag shipped for archival outputs  
- **Honest marketing** — never claim W-9/HR success without fixtures that prove it  

---

## Phase 0 — Unblock trust (this foundation PR)

**Status:** Done (foundation PR).

**Outcome:** CI green; install story honest; writer follows pypdf guidance; roadmap published.

| # | Work | Why |
|---|------|-----|
| 0.1 | Pin Ruff; explicit `[tool.ruff.lint]`; fix/autofix lint | Floating Ruff breaks CI |
| 0.2 | Prefer Ruff format (or document Black-only) — one formatter | Avoid dual-formatter drift |
| 0.3 | Export **local** `fill()` via `run_fill_pipeline`; keep `PDFAutofillerClient` for HTTP | README/recipes must work offline |
| 0.4 | Add `py.typed` | Match `Typing :: Typed` classifier |
| 0.5 | `auto_regenerate=False` on form writes | Avoid “save changes” dialogs ([pypdf forms docs](https://pypdf.readthedocs.io/en/stable/user/forms.html)) |
| 0.6 | Align `allow_fallback_mapping` defaults (API/library/pipeline = `False`) | Surprise AI/network calls |
| 0.7 | Fix docs drift (`TESTING.md` audit ignore, `OPERATIONS.md` proxy headers) | Accuracy |
| 0.8 | `Makefile` / scripts use `python3` | Portability |
| 0.9 | Auth **before** rate-limit counting; `Retry-After` on 429 | FastAPI production practice |
| 0.10 | `POST /inspect` — list fields (name, type, required, page) | Onboarding loop |
| 0.11 | Playground: safer status DOM, password API key, error codes, sample PDF link | UX + XSS hygiene |
| 0.12 | Ship `samples/` in Docker image; `docker-compose.yml` for one-command try | Discovery → value |
| 0.13 | README: accurate test counts, local vs remote fill, Quickstart ≤3 steps | Conversion |

**Exit criteria:** `make lint && make test && make smoke-check` green; `pip install -e .` then `from pdf_autofiller import fill` works without a server; `/inspect` + playground sample path work.

---

## Phase 1 — Deliver diagnosable value

**Status:** Partial — shipped in 0.5.0: `/preview`, choice write path, flatten, playground Preview Mapping + fill-report panel (written / skipped-review / skipped-empty from response headers), OpenAPI `200 application/pdf`, ops clarifications. Still open: **1.2** Accept/JSON body fill report (headers + playground panel are the current report surface); **1.4** OpenAPI error catalog.

**Outcome:** Users can open any AcroForm, see fields, preview mapping, and debug misses.

| # | Work | Why | Status |
|---|------|-----|--------|
| 1.1 | `POST /preview` — mapping decisions JSON without writing PDF | Debug without round-trips | Done |
| 1.2 | Optional JSON fill report body / `Accept` negotiation | Headers alone are too weak for ops | Open (headers + playground panel interim) |
| 1.3 | Playground panel: field inventory + written/skipped/missing | Visual proof | Done (inspect + fill report panel) |
| 1.4 | OpenAPI: document `200 application/pdf` + error catalog | SDK/codegen consumers | Partial (`200` PDF done; error catalog open) |
| 1.5 | Choice (`/Ch`) write path; document signature (`/Sig`) limits | Completeness | Done |
| 1.6 | Alias reload or documented import-time caveat for `FORM_ALIASES_DIR` | Ops correctness | Done (documented) |
| 1.7 | Rename/clarify `PDF_READ_TIMEOUT_SECONDS` (covers full pipeline) | Honest ops | Done |

**Exit criteria:** New user fills an unknown PDF using inspect → edit JSON → preview → fill with zero Slack help.

---

## Phase 2 — Prove accuracy on real forms

**Status:** Done for synthetic corpus (sample_form + hr_intake) — `tests/fixtures/corpus/`, `make corpus-check`. Redacted real W-9 still optional follow-up.

**Outcome:** Marketing claims are backed by CI fixtures.

| # | Work | Why |
|---|------|-----|
| 2.1 | Golden corpus: synthetic `sample_form` + HR intake fixtures + expected maps | Trust |
| 2.2 | Hit-rate report in CI (`scripts/corpus_report.py`) | Regression signal |
| 2.3 | Expand alias packs from corpus field names | Deterministic lift |
| 2.4 | Recipes updated with real field inventories from `/inspect` | Accuracy |
| 2.5 | Optional flatten flag for archival outputs | Common production need |

**Exit criteria:** CI publishes ≥N-form hit rate; W-9 recipe runs against a shipped fixture.

---

## Phase 3 — Distribution & discoverability

**Status:** Partial — FAQ, integrations copy-paste, Pages links, honest PyPI note. Hosted demo GIF / star metrics still later.

**Outcome:** Strangers find and install the project.

Aligned with OSS discovery practice ([GitHub SEO / README conversion](https://claudegithub.com/blog-github-seo-keywords)):

| # | Work | Why |
|---|------|-----|
| 3.1 | Reliable PyPI publish (no silent `continue-on-error`); README `pip install pdf-autofiller` | Install path |
| 3.2 | Hosted demo (rate-limited) or Codespaces one-click still primary | Try without clone |
| 3.3 | Short demo GIF/video above the fold | 10-second conversion |
| 3.4 | FAQ + comparison (“vs AI-only fillers / SaaS”) | Search + objections |
| 3.5 | n8n/Zapier copy-paste templates that actually run | Workflow users |
| 3.6 | Fix GitHub Pages deploy; link API.md + recipes from site | Docs hub |
| 3.7 | Star history / usage proof once metrics exist | Social proof |

**Exit criteria:** Cold visitor: find via search → install → filled PDF in &lt;5 minutes.

---

## Phase 4 — Production hardening

**Status:** Partial — JSON logs (`LOG_FORMAT=json`), security headers, multi-worker rate-limit docs, docker CI smoke. Pydantic Settings skipped (env vars remain as-is); narrowing `except Exception` deferred.

**Outcome:** Multi-instance deployments are safe by default.

| # | Work | Why |
|---|------|-----|
| 4.1 | Document Redis/ingress rate limiting; keep in-process as single-worker fallback | Scale |
| 4.2 | Pydantic Settings for config (typed env) | FastAPI production pattern |
| 4.3 | Structured JSON logging option | Ops |
| 4.4 | Security headers middleware | Defense in depth |
| 4.5 | CI: `docker build` + health smoke; optional Playwright playground | Ship confidence |
| 4.6 | Narrow `except Exception` to expected types where safe | Maintainability |

---

## Feature checklist (every new feature)

Before merging any feature, verify:

- [ ] Tests cover success + failure contracts  
- [ ] Docs/API/OpenAPI updated in the same PR  
- [ ] Defaults are safe (no surprise network/AI)  
- [ ] Errors use `{detail: {error: {code, message, details}}}`  
- [ ] No PII in logs  
- [ ] Lint + mypy clean under pinned tools  
- [ ] README example still runs as written  

## Suggested sequencing for contributors

```text
Phase 0 (foundation) ──► Phase 1 (inspect/preview UX) ──► Phase 2 (corpus)
         │                                                      │
         └──────────► Phase 3 (PyPI / demo) ◄───────────────────┘
                              │
                              ▼
                         Phase 4 (scale)
```

## Success metrics

| Metric | Baseline | Target |
|--------|----------|--------|
| CI green on `main` | Lint flaky/red under new Ruff | Always green |
| Time to first filled PDF | Clone + guess field names | &lt;5 min with sample + inspect |
| Offline `fill()` works | No | Yes |
| Real-form fixture coverage | 1 synthetic sample | ≥5 real AcroForms |
| PyPI install | Broken/unreliable | Documented + CI-verified |
| Alias synonym accuracy | Fixed in alias PR | Covered by regression tests |

## Related docs

- [PURPOSE.md](PURPOSE.md) — problem framing  
- [ARCHITECTURE.md](ARCHITECTURE.md) — module boundaries  
- [API.md](API.md) — HTTP contract  
- [FAQ.md](FAQ.md) — comparisons and common questions  
- [OPERATIONS.md](OPERATIONS.md) — deployment  
- [TESTING.md](TESTING.md) — quality gates  
