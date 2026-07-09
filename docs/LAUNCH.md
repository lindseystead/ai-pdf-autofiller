# Launch Playbook

Ready-to-post copy for Hacker News, Reddit, and Product Hunt.

## One-liner

**Open-source API that fills any government or HR PDF from JSON — no manual field mapping.**

## Hacker News (Show HN)

**Title:** Show HN: PDF Autofiller – fill any AcroForm PDF from JSON (deterministic-first, optional AI)

**Post body:**

I got tired of writing one-off scripts every time a client sent a PDF with field names like `txtFName` and `field_12`. Built a small FastAPI service that:

- Normalizes keys and matches via aliases (W-9, HR onboarding packs included)
- Coerces dates/numbers/booleans with review flags for ambiguous values
- Optionally uses AI for opaque field names (PII-minimized — key names only)
- Returns a filled PDF + diagnostics headers

Try it locally in 30 seconds:

```
git clone https://github.com/lindseystead/ai-pdf-autofiller
make run-api
open http://localhost:8000/playground
```

Or Python:

```python
from pdf_autofiller import fill
fill("w9.pdf", {"name_line_1": "Jane Doe", "ssn": "..."}, "filled.pdf")
```

MIT licensed, 85%+ test coverage, auth on by default. Would love feedback on which form families to add alias packs for next.

**Link:** https://github.com/lindseystead/ai-pdf-autofiller

## Reddit r/selfhosted

**Title:** Self-hosted PDF form filler API — upload any fillable PDF + JSON, get completed PDF back

**Body:**

Built an open-source microservice for a problem I kept hitting: every PDF form uses different field names, and mapping them by hand doesn't scale.

**What it does:**
- POST a PDF + JSON profile → get filled PDF
- Deterministic matching first (free, auditable)
- Optional AI for weird field names
- Web playground UI at `/playground`
- Docker + Render deploy ready

**Stack:** Python, FastAPI, pypdf. No database needed.

**Quick start:**
```bash
docker build -t pdf-autofiller .
docker run -p 8000:8000 -e API_AUTH_ENABLED=false pdf-autofiller
```

Recipes for W-9 and HR onboarding included. MIT license.

Repo: https://github.com/lindseystead/ai-pdf-autofiller

Happy to add alias packs for forms people actually use — drop suggestions in issues.

## Product Hunt

**Tagline:** Fill any PDF form from JSON in one API call

**Description:**

PDF Autofiller is an open-source engine for programmatic PDF form completion. Upload a fillable PDF and structured user data — get a completed document back without writing field-by-field mapping code.

**Key features:**
- Deterministic-first mapping with 25+ semantic concepts
- Community alias packs (W-9, HR onboarding)
- Browser playground for instant demos
- Python SDK: `pip install pdf-autofiller`
- Self-host with Docker or Render

**Maker comment:** Built this after the third client asked me to "just auto-fill their PDFs." The deterministic path handles most fields; AI is opt-in for the weird ones.

## Twitter / X thread (5 posts)

1. Every PDF form uses different field names. `first_name` vs `txtFName` vs `field_12`. I built an open-source fix. 🧵

2. PDF Autofiller: upload PDF + JSON → filled PDF. Deterministic matching first. AI only when you need it. MIT licensed.

3. Try it in the browser: `/playground` — drag, drop, paste JSON, download. No install.

4. Python SDK in 3 lines:
```python
from pdf_autofiller import fill
fill("form.pdf", {"firstname": "Jane"}, "filled.pdf")
```

5. Recipes for W-9 and HR onboarding included. Star the repo if this saves you a afternoon of pypdf scripting: github.com/lindseystead/ai-pdf-autofiller

## Launch checklist

- [ ] Deploy playground to Render (see `render.yaml`)
- [ ] Record 30-second demo GIF for README
- [ ] Post Show HN (Tuesday–Thursday, US morning)
- [ ] Cross-post to r/selfhosted, r/Python, r/golang (if SDK expands)
- [ ] Submit Product Hunt
- [ ] Publish `pdf-autofiller` to PyPI (GitHub Actions on release tag)
