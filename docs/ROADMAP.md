# Roadmap (lean)

Bring this from early-senior beta to production-quality **with two real work items**. Everything else is either done or deliberately skipped.

## Already good enough (do not rebuild)

- Library + HTTP inspect → preview → fill  
- Fail-closed auth, upload/size/page/timeout guards, error catalog  
- Synthetic corpus in CI, Release wheels + GHCR  
- Deterministic-first; AI opt-in  
- Docs that mostly match the code  

## Do next (only this)

### 1. Honest fill reports — **bugfix, not a feature**

`pdf_writer` can skip mapped values (bad checkbox state, missing widget, `/Sig`) without naming them in `FillReport`.

- Add those skips to the existing report (one list + reason is enough)  
- Two unit tests  
- Fix any leftover “IRS W-9” marketing slips in recipes  

**Done when:** a successful fill never drops a mapped value silently.

### 2. One non-circular fixture — **proof, not a corpus empire**

Add **one** AcroForm whose field names come from a real inspect dump (or a redacted real file). Wire it into the existing `cases.json` pattern. Update the matching recipe from `/inspect` only.

**Done when:** at least one CI fixture was not invented solely to match alias packs.

## When you have two minutes (not a phase)

- Enable PyPI Trusted Publisher + run the existing manual workflow  
- Or keep `make install-release` — already honest  

## Do not do (this would be over-engineering)

- OCR / scanned PDFs  
- Redis / shared rate limiter in-app  
- Pydantic Settings rewrite  
- Playwright CI, hosted demo SaaS, microservices  
- Second/third “vendor-like” fixtures until someone hits a real miss  
- Narrowing every `except Exception` for its own sake  
- Splitting `routes.py` or inventing a plugin system  

## Production-quality bar for *this* repo

1. Fill reports tell the truth  
2. One evidence-backed fixture in CI  
3. README install path works (Release wheel or PyPI)  
4. Scope stays AcroForm + deterministic-first  

That is senior judgment: fix the lie, prove the claim, ship. Stop.

## Related

- [PURPOSE.md](PURPOSE.md) · [ARCHITECTURE.md](ARCHITECTURE.md) · [OPERATIONS.md](OPERATIONS.md) · [RELEASE.md](RELEASE.md) · [TESTING.md](TESTING.md)
