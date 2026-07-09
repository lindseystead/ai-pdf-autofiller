# Show HN — ready to post

**When:** Tuesday–Thursday, 8:00–10:00 AM US Eastern  
**Before posting:** replace `https://YOUR-SERVICE.onrender.com` below with your live Render URL.

---

## Title (pick one)

**Recommended:**
```
Show HN: Fill any PDF form from JSON – no manual field mapping
```

**Alternatives:**
```
Show HN: PDF Autofiller – upload PDF + JSON, get a filled form back
```
```
Show HN: I got tired of mapping txtFirstName – built a PDF form filler API
```

---

## URL field

Post the **playground**, not just the repo (lower friction):

```
https://YOUR-SERVICE.onrender.com/playground
```

Example after deploy: `https://pdf-autofiller.onrender.com/playground`

If playground isn't live yet, use the repo:

```
https://github.com/lindseystead/ai-pdf-autofiller
```

---

## Body (copy-paste)

```
I kept writing one-off pypdf scripts every time a client sent a form with field names like txtFName and field_12. Built a small service that maps JSON user data to AcroForm fields without hand-written mappings.

Try it in the browser (no install):
https://YOUR-SERVICE.onrender.com/playground

Or locally:
  git clone https://github.com/lindseystead/ai-pdf-autofiller
  make run-api

What it does:
- Normalizes keys + alias packs (W-9, HR onboarding included)
- Coerces dates/numbers; flags ambiguous values for review
- Optional AI for opaque field names (PII-minimized – key names only, not values)
- Returns filled PDF + diagnostic headers

Python SDK:
  pip install pdf-autofiller
  from pdf_autofiller import fill
  fill("form.pdf", {"firstname": "Jane"}, "filled.pdf")

MIT, 85%+ test coverage, auth on by default, Docker + Render deploy.

Would love feedback: which form families should we add alias packs for next? W-9 and HR are in the repo; thinking CMS-1500, I-9 supplements, state tax forms.

Repo: https://github.com/lindseystead/ai-pdf-autofiller
```

---

## First comment (post immediately after submission)

HN sometimes buries the link. Post this as the first comment:

```
Live playground: https://YOUR-SERVICE.onrender.com/playground

Recipes (W-9, HR): https://github.com/lindseystead/ai-pdf-autofiller/tree/main/recipes
```

---

## How to respond to common HN comments

| Comment | Reply angle |
|---------|-------------|
| "How is this different from pypdf?" | We wrap normalization, aliases, type coercion, required-field enforcement, and HTTP API – the boring glue everyone rewrites. |
| "What about scanned PDFs?" | AcroForm only today; OCR is out of scope. Works on fillable government/HR PDFs. |
| "AI privacy?" | Deterministic path needs no API key. AI fallback sends key *names* and types only, never values. |
| "DocuSign?" | Fill-only, no signatures/workflows. Self-hosted, no per-envelope fees. Comparison in repo docs. |
| "Field X didn't map" | Open an issue with the PDF – we're adding community alias packs. |

---

## After posting

- [ ] Reply to every comment for 4+ hours
- [ ] Fix any reported bugs same day
- [ ] Cross-post to r/selfhosted (see LAUNCH.md) once HN thread is live
- [ ] Add "Discussed on HN" link to README optional badge after thread URL exists
