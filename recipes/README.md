# PDF Autofiller Recipes

Copy-paste examples against **shipped sample PDFs**. Each recipe’s field inventory comes from `inspect()` / `POST /inspect` on that file.

| Recipe | Fixture | Notes |
|--------|---------|--------|
| [sample-form.sh](sample-form.sh) | `samples/sample_form.pdf` | Bundled demo; ~30 seconds |
| [w9.md](w9.md) | `samples/w9_shaped_sample.pdf` | Synthetic W-9-**shaped** fields + `w9.json` — **not** an official IRS W-9 |
| [hr-onboarding.md](hr-onboarding.md) | `samples/hr_intake_sample.pdf`, `samples/hr_hire_alias_sample.pdf` | Synthetic HR intake — not a vendor HRIS PDF |
| [vendor-opaque.md](vendor-opaque.md) | `samples/vendor_opaque_sample.pdf` | Opaque export-style widget names from an anonymized inspect dump |

## Prerequisites

```bash
API_AUTH_ENABLED=false make run-api
# Playground UI: http://localhost:8000/playground
```

If you enable auth for a closer-to-production local run, export your key:

```bash
export API_AUTH_TOKEN=your-token
```

## Tips

1. Use **strict=true** first — deterministic mapping is free and auditable.
2. Enable **semantic inference** only when field names are opaque and aliases do not cover them.
3. Check response headers: `X-PDF-Fields-Written`, `X-PDF-Fields-Skipped-Review`, `X-PDF-Fields-Skipped-Empty`, `X-PDF-Fields-Skipped-Unwritable`.
4. Missing required fields return `422` with `required_fields_unresolved` — fix your JSON and retry.
5. Golden fixtures and expectations: `tests/fixtures/corpus/cases.json` (`make corpus-check`).
