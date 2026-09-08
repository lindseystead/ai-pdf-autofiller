# Roadmap: early-senior → production quality

This plan takes PDF Autofiller from a solid **early-senior beta** to **production-quality** work without turning it into a platform rewrite.

Grounded in the current codebase (`pipeline` / `api/` / writer / corpus), E2E verification, and the honesty gaps that still separate “works on our samples” from “teams would run this in prod.”

## Goals

1. **Correct** — fill reports tell the truth; required fields cannot silently vanish  
2. **Proven** — claims match fixtures that are not self-fulfilling  
3. **Installable** — one supported install path strangers can trust  
4. **Operable** — single-node deploy is safe by default; scale limits are documented, not faked  
5. **Maintainable** — small modules, pinned lint/types/tests; no dual truth in docs  

## Non-goals (deliberate — avoid over-engineering)

- OCR / scanned PDFs  
- Multi-tenant SaaS, billing, or hosted AI gateway  
- Mandatory Redis / shared cache in-process  
- Full Pydantic Settings rewrite unless env drift becomes painful  
- Microservices, event buses, or plugin frameworks  
- “Any PDF / official IRS certification” marketing  

## Principles

- Deterministic-first; AI remains opt-in  
- Docs = code; fail closed on auth/size/pages/timeout  
- Prefer fixing report honesty and real fixtures over new features  
- One change class per phase; exit criteria must be measurable  

## Current baseline (0.6.1)

| Area | Status |
|------|--------|
| Library + HTTP inspect/preview/fill | Done |
| Error catalog, upload/DoS guards, fail-closed auth | Done |
| Synthetic corpus 5/30 in CI | Done |
| Release wheels + GHCR; PyPI manual/deferred | Done (honest) |
| Writer report gaps (button/Sig/object misses) | Open |
| Real / redacted vendor fixtures | Open |
| Docs marketing slips (e.g. recipes table vs W-9 honesty) | Open |

Phases 0–2 in the historical roadmap (foundation, inspect/preview, synthetic corpus) are **complete**. What follows is the remaining path.

---

## Phase A — Make the write path trustworthy

**Why first:** Production quality starts with “the report matches the PDF.” Architecture is already fine; silent skips in `pdf_writer.py` are the highest-leverage correctness gap.

| # | Work | Why | Anti-complexity note |
|---|------|-----|----------------------|
| A.1 | Track unresolved checkbox/radio values, missing field objects, and `/Sig` skips in `FillReport` (new explicit lists or a single `skipped_unwritable_fields` + reasons) | Callers can detect lies-by-omission | Extend existing report model; no new service |
| A.2 | Warn (log) + surface counts on API JSON fill / headers when decisions &gt; writes | Ops visibility | Reuse audit log; no new telemetry stack |
| A.3 | Unit tests: decision present but widget missing / bad button state → appears in report | Prevent regressions | |
| A.4 | Fix remaining docs honesty (`recipes/README.md` W-9 row, any “IRS” claim without real fixture) | Trust | Doc-only |

**Exit criteria:** No successful fill can drop a mapped value without naming that field in the report. Tests cover at least two skip classes. Marketing language matches `ARCHITECTURE.md` / `PURPOSE.md`.

**Effort shape:** Writer + models + a handful of tests + doc nits. No API redesign.

---

## Phase B — Prove value beyond self-generated forms

**Why next:** Senior work is evidence-backed. Synthetic `txt*` fixtures that mirror alias packs prove the pipeline, not template diversity.

| # | Work | Why | Anti-complexity note |
|---|------|-----|----------------------|
| B.1 | Add **≥1 redacted real AcroForm** *or* a synthetic form whose field names were taken from a real inspect dump (not invented to match aliases) | Breaks circular proof | One hard fixture beats ten soft ones |
| B.2 | Corpus case + expected writes for that fixture; aliases only where inspect justifies them | CI regression | Same `cases.json` pattern |
| B.3 | Recipe updated from `/inspect` inventory only | Docs = code | |
| B.4 | Optional second fixture (HR vendor-like) if B.1 was tax-shaped — stop at two unless hit rate demands more | Depth over breadth | |

**Exit criteria:** README/recipes that mention a form family point at a fixture that was not hand-built solely to match the pack. Corpus CI still green.

**Out of scope here:** Buying form libraries, OCR, or claiming government certification.

---

## Phase C — Distribution that matches the product

**Why:** Quality nobody can install is not production quality for OSS. Do the minimum that makes `pip` or Release wheels the single clear story.

| # | Work | Why | Anti-complexity note |
|---|------|-----|----------------------|
| C.1 | When ready: one-time PyPI Trusted Publisher (`environment: pypi`) + `workflow_dispatch` green + re-enable release trigger | Standard install | Already wired; operator step only |
| C.2 | Until C.1: keep README primary path = `make install-release` / Release wheels | No false `pip install` | Already done — maintain |
| C.3 | Short demo artifact (terminal transcript already exists; optional GIF) linked above the fold | Conversion | Do not build a hosted multi-tenant demo |
| C.4 | Keep Pages skip-if-disabled; enable Pages when convenient | Docs hub | No custom docs platform |

**Exit criteria:** Cold path documented in README works in &lt;5 minutes on a clean machine (Release wheel *or* PyPI — whichever is live). CI does not go red on Release because of PyPI.

---

## Phase D — Production ops polish (thin)

**Why last:** Hardening that helps operators, without redesigning the stack.

| # | Work | Why | Anti-complexity note |
|---|------|-----|----------------------|
| D.1 | Narrow `except Exception` in reader/writer/acroform **only** where the expected pypdf errors are known; leave a documented broad catch at the PDF boundary | Maintainability | Do not invent a custom PDF error hierarchy |
| D.2 | Startup validation for numeric env bounds (pages, bytes, timeout) — small helper or keep getenv + clamp/fail | Misconfig fails fast | Full Settings model still optional |
| D.3 | Remove stale `api_service` test-only re-exports; tests import from `api.*` | Cleaner boundary | No route rewrite required |
| D.4 | Confirm OPERATIONS docs: in-process rate limit = single worker; use ingress/Redis *outside* the app for multi-instance | Honest scale | Do not implement Redis client in-app unless a real deployer needs it |
| D.5 | Optional: Playwright smoke for playground **only if** UI regressions recur | Confidence | Prefer HTTP contract tests; skip if stable |

**Exit criteria:** Fresh deploy with bad env fails clearly; library/API boundary has no historical re-export debt; ops docs match runtime.

---

## Sequencing

```text
Phase A (write-report truth) ──► Phase B (real-ish proof)
         │                              │
         └──────────► Phase C (install) ◄┘
                              │
                              ▼
                    Phase D (thin ops polish)
```

Do **not** start D before A. Do **not** block A/B on PyPI. C can overlap B once A is merged.

## Definition of “senior / production quality” for this repo

Ship when all are true:

1. Fill reports cannot omit unwritable mapped fields (A)  
2. At least one non-circular form fixture is in CI (B)  
3. Install path in README works without tribal knowledge (C)  
4. Single-node production deploy is documented and fail-closed; scale limits are explicit (D)  
5. Scope stays AcroForm + deterministic-first — no OCR/SaaS creep  

That bar is **production-quality for a focused library + optional API**, not “enterprise PDF platform.”

## Feature checklist (unchanged)

Before merging any feature:

- [ ] Tests cover success + failure contracts  
- [ ] Docs/OpenAPI updated in the same PR  
- [ ] Defaults safe (no surprise network/AI)  
- [ ] Errors use `{detail: {error: {code, message, details}}}`  
- [ ] No PII in logs  
- [ ] Lint + mypy clean under pinned tools  
- [ ] README example still runs as written  

## Related docs

- [PURPOSE.md](PURPOSE.md) — problem framing  
- [ARCHITECTURE.md](ARCHITECTURE.md) — module boundaries  
- [API.md](API.md) — HTTP contract  
- [OPERATIONS.md](OPERATIONS.md) — deployment  
- [RELEASE.md](RELEASE.md) — release / PyPI deferral  
- [TESTING.md](TESTING.md) — quality gates  
- [FAQ.md](FAQ.md) — comparisons  
