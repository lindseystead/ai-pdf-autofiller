# Vendor-opaque field names (inspect-derived)

Fixture: `samples/vendor_opaque_sample.pdf`

Field names were taken from an **anonymized vendor intake inspect dump**. The PDF page is a blank synthetic AcroForm (not the vendor’s file). JSON keys are the widget names — no special alias pack for this case.

## Field inventory (`POST /inspect`)

| Field | Type | Required |
|-------|------|----------|
| `EmployeeFirstName_AF_text` | text | yes |
| `EmployeeLastName_AF_text` | text | yes |
| `DateOfBirth_AF_date` | text | yes |
| `EmailAddress_AF_text` | text | no |
| `PrimaryPhone_AF_text` | text | no |

## curl

```bash
API_AUTH_ENABLED=false make run-api   # other terminal

curl -s -X POST http://localhost:8000/fill \
  -F "pdf_file=@samples/vendor_opaque_sample.pdf;type=application/pdf" \
  -F 'user_data={"EmployeeFirstName_AF_text":"Pat","EmployeeLastName_AF_text":"Nguyen","DateOfBirth_AF_date":"1990-01-01","EmailAddress_AF_text":"pat@example.com","PrimaryPhone_AF_text":"555-0199"}' \
  -o vendor_opaque_filled.pdf
```

## Library

```python
from pdf_autofiller import fill, preview

profile = {
    "EmployeeFirstName_AF_text": "Pat",
    "EmployeeLastName_AF_text": "Nguyen",
    "DateOfBirth_AF_date": "1990-01-01",
    "EmailAddress_AF_text": "pat@example.com",
    "PrimaryPhone_AF_text": "555-0199",
}
assert not preview("samples/vendor_opaque_sample.pdf", profile).mapping.missing_required
fill("samples/vendor_opaque_sample.pdf", profile, "vendor_opaque_filled.pdf")
```
