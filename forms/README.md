# Community Form Alias Packs

These JSON files extend deterministic field matching for common form families. They ship with the package under `src/pdf_autofiller/form_aliases/` and are merged into `FIELD_ALIASES` at import time.

## Built-in packs

| Pack | File | Covers |
|------|------|--------|
| IRS W-9 | `w9.json` | Taxpayer name, EIN, business name, exemptions |
| HR onboarding | `hr_onboarding.json` | Emergency contact, hire date, manager, employee ID |

## Contribute a pack

1. Copy an existing JSON file and rename it for your form family (e.g. `cms1500.json`).
2. Keys are **canonical semantic meanings** (snake_case).
3. Values are **arrays of user-data key variants** your clients might send.
4. Open a PR with a short note about which PDF(s) you tested against.

## Custom alias directory

Set `FORM_ALIASES_DIR` to load additional packs from your deployment:

```bash
export FORM_ALIASES_DIR=/etc/pdf-autofiller/aliases
```

Each `*.json` file in that directory is merged the same way.

## Example user data for W-9

```json
{
  "name_line_1": "Jane Doe",
  "business_name_line_2": "Doe Consulting LLC",
  "tax_classification": "individual",
  "addr1": "123 Main St",
  "town": "Springfield",
  "province": "IL",
  "zipcode": "62701",
  "ssn": "123-45-6789"
}
```

See [recipes/w9.md](../recipes/w9.md) for a full curl recipe.
