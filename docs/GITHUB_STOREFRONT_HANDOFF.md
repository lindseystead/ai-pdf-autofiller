# Handoff: GitHub storefront (admin only)

**For Claude / repo admin:** almost all agent work is already on `main` (through **v0.6.3**). What remains is GitHub **Settings / About** work that a cloud agent token cannot do (`403 Resource not accessible by integration`).

Do **not** re-implement product/code polish from PRs #44–#47. That is already merged.

## Already on `main` (do not redo)

| Squash on `main` | What landed |
|------------------|-------------|
| `b5c0d22` (#44) | Fill honesty, process-isolated PDF timeouts, batched semantics, choice unmatched handling |
| `e607d79` (#45) | Default-path date typing, doc accuracy |
| `bc8b67e` (#46) | NeedAppearances default, opaque field hints, `RATE_LIMIT_BACKEND=file` |
| `f718794` (#47) | Recruiter packaging polish for **v0.6.3** |

Also published: GitHub Release **`v0.6.3`** (wheel + sdist). Assets under `docs/assets/` (playground + social preview PNGs, demo transcript) are in the repo.

## Still broken on the live GitHub storefront

Verify: https://github.com/lindseystead/ai-pdf-autofiller

| Item | Current (bad) | Target |
|------|---------------|--------|
| About **description** | Still says “Fill **any** AcroForm PDF…” | Softened copy (no “any”) — see script below |
| **Homepage** URL | `https://lindseystead.github.io/ai-pdf-autofiller/` (**404** — Pages not enabled) | Clear to empty **or** enable Pages then set URL |
| **Social preview** | Not uploaded in Settings | Upload `docs/assets/social-preview.png` |
| Stale open PRs | #31 (draft recruiter polish), #32 (stale model-path review), #48 (superseded by #49 handoff) | Close as superseded |

## What you should run (repo admin `gh` login)

From the repo root, with **your** GitHub account that has admin on the repo (not the cloud agent token):

```bash
# Preferred: description + topics + clear broken homepage
bash scripts/apply-repo-metadata.sh

# Also closes stale PRs #31 and #32 if still open
bash scripts/fix-github-storefront.sh
```

Then **manually in the UI** (API cannot upload social preview):

1. **Settings → General → Social preview** → upload `docs/assets/social-preview.png`
2. Optional: **Settings → Pages → Source = GitHub Actions**, wait for the Pages workflow, then set homepage to `https://lindseystead.github.io/ai-pdf-autofiller/`

If you skip Pages, leave homepage blank (a 404 is worse for recruiters than no link).

## Product facts to keep honest (do not re-hype)

- AcroForm fill only — not OCR / scanned PDFs
- Deterministic-first; AI optional and off by default
- `strict` = AI-fallback only; required fields still enforced
- Corpus is synthetic (W-9-**shaped**, not IRS-certified)

## History note

Repo uses **squash merges** into `main`. Do not rewrite old `main` history; keep clean squash subjects.
