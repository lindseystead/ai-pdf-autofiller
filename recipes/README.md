# PDF Autofiller Recipes

Copy-paste recipes for filling common PDF forms. Each recipe assumes the API is running locally or on your deployed playground.

| Recipe | Form | Difficulty |
|--------|------|------------|
| [w9.md](w9.md) | IRS Form W-9 | Easy |
| [hr-onboarding.md](hr-onboarding.md) | Generic HR intake | Easy |
| [sample-form.sh](sample-form.sh) | Bundled demo PDF | 30 seconds |

## Prerequisites

```bash
make run-api
# Playground UI: http://localhost:8000/playground
```

If auth is enabled, export your key:

```bash
export API_AUTH_TOKEN=your-token
```

## Tips for any recipe

1. Use **strict=true** first — deterministic mapping is free and auditable.
2. Enable **semantic inference** only when field names are opaque (`field_12`, `Text1`).
3. Check response headers: `X-PDF-Fields-Written`, `X-PDF-Fields-Skipped-Review`.
4. Missing required fields return `422` with `required_fields_unresolved` — fix your JSON and retry.

## Python SDK (3 lines)

```python
from pdf_autofiller import fill

fill("form.pdf", {"firstname": "Jane", "lastname": "Doe"}, "filled.pdf")
```

## Share your recipe

Add a new file under `recipes/` and open a PR. Include the JSON schema you used and which PDF version you tested.
