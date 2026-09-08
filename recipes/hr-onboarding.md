# Fill HR onboarding PDFs from JSON

Generic recipe for employee intake packets. CI proves two **synthetic** fixtures —
not vendor HRIS PDFs.

## Corpus fixtures (from `/inspect`)

### `samples/hr_intake_sample.pdf`

| Field | Type | Required | Example JSON keys |
|-------|------|----------|-------------------|
| `txtEmployeeName` | text | yes | `employee_name`, `worker_name` |
| `txtSSN` | text | yes | `ssn` |
| `txtEmployer` | text | yes | `employer`, `company` |
| `txtJobTitle` | text | no | `job_title`, `position` |
| `txtStartDate` | text | no | `start_date`, `hire_date` |
| `chkConsent` | button | no | `consent`, `agree` |

### `samples/hr_hire_alias_sample.pdf`

| Field | Type | Required | Example JSON keys |
|-------|------|----------|-------------------|
| `txtEmployeeName` | text | yes | `worker_name` |
| `txtStartDate` | text | yes | `hire_date` |
| `txtManager` | text | no | `supervisor`, `manager` |
| `txtDepartment` | text | no | `dept`, `department` |
| `txtEmployeeId` | text | no | `badge_number`, `emp_id` |

## curl (hire-date aliases)

```bash
API_AUTH_ENABLED=false make run-api   # other terminal

curl -s -X POST http://localhost:8000/fill \
  -F "pdf_file=@samples/hr_hire_alias_sample.pdf;type=application/pdf" \
  -F 'user_data={"worker_name":"Pat Nguyen","hire_date":"2026-04-15","supervisor":"Alex Manager","dept":"Engineering","badge_number":"E-2048"}' \
  -o hr_hire_filled.pdf
```

## Library

```python
from pdf_autofiller import fill, preview

profile = {
    "employee_name": "Jane Doe",
    "ssn": "123-45-6789",
    "employer": "Acme Corp",
    "job_title": "Software Engineer",
    "start_date": "2026-03-01",
    "consent": True,
}
assert not preview("samples/hr_intake_sample.pdf", profile).mapping.missing_required
fill("samples/hr_intake_sample.pdf", profile, "hr_intake_filled.pdf")
```

## Alias pack

`src/pdf_autofiller/form_aliases/hr_onboarding.json` — contribute new synonyms with a corpus case.
