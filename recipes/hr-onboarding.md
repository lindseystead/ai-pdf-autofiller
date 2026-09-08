# Fill HR onboarding PDFs from JSON

Generic recipe for employee intake packets (I-9 supplements, benefits enrollment, emergency contacts).

## User data template

```json
{
  "firstname": "Jane",
  "lastname": "Doe",
  "dob": "1990-05-15",
  "email": "jane.doe@company.com",
  "phone": "555-0100",
  "addr1": "123 Main St",
  "town": "Springfield",
  "province": "IL",
  "zipcode": "62701",
  "hire_date": "2026-03-01",
  "position": "Software Engineer",
  "department": "Engineering",
  "manager": "Alex Morgan",
  "emergency_contact": "John Doe",
  "emergency_phone": "555-0199",
  "employee_id": "EMP-1042"
}
```

## curl

Start the API without a token for local demos (`API_AUTH_ENABLED=false make run-api`), then:

```bash
curl -s -X POST http://localhost:8000/fill \
  -F "pdf_file=@onboarding.pdf;type=application/pdf" \
  -F 'user_data={
    "firstname": "Jane",
    "lastname": "Doe",
    "email": "jane.doe@company.com",
    "hire_date": "2026-03-01",
    "position": "Software Engineer",
    "emergency_contact": "John Doe"
  }' \
  -F "strict=true" \
  -o onboarding-filled.pdf
```

When auth is enabled, add `-H "X-API-Key: ${API_AUTH_TOKEN}"`.

## Python SDK

```python
from pdf_autofiller.client import PDFAutofillerClient

client = PDFAutofillerClient("http://localhost:8000", api_key="your-token")
client.fill_to_file("onboarding.pdf", {
    "firstname": "Jane",
    "lastname": "Doe",
    "hire_date": "2026-03-01",
}, "onboarding-filled.pdf")
```

## Alias pack

HR-specific aliases ship in `src/pdf_autofiller/form_aliases/hr_onboarding.json`.

## Synthetic fixture

A CI/demo HR intake PDF lives at `samples/hr_intake_sample.pdf` (fields: `txtEmployeeName`, `txtSSN`, `txtEmployer`, `txtJobTitle`, `txtStartDate`, `chkConsent`). Expected maps are in `tests/fixtures/corpus/cases.json`. Regenerate with `python3 scripts/create_corpus_forms.py`.
