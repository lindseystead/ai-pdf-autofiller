# Sample PDFs

Synthetic AcroForms for demos and the golden corpus. **Not** official IRS or vendor PDFs.
Each is one page with a title, labels and boxes; `tests/test_samples.py` checks they stay that way.

## Files

| File | Generator | Role |
|------|-----------|------|
| `sample_form.pdf` | `scripts/create_sample_forms.py` | Demo name/contact fields |
| `hr_intake_sample.pdf` | `scripts/create_sample_forms.py` | HR intake + checkbox |
| `w9_shaped_sample.pdf` | `scripts/create_sample_forms.py` | W-9-shaped names + `w9.json` pack |
| `address_contact_sample.pdf` | `scripts/create_sample_forms.py` | Address/email/phone aliases |
| `hr_hire_alias_sample.pdf` | `scripts/create_sample_forms.py` | HR pack hire_date/manager synonyms |
| `vendor_opaque_sample.pdf` | `scripts/create_sample_forms.py` | Opaque names from anonymized inspect dump |

Expectations: `tests/fixtures/corpus/cases.json` · report: `make corpus-check` (6 cases / 35 expected field writes).

## Usage

```bash
python3 -m scripts.create_sample_forms  # regenerate all samples
PYTHONPATH=src python3 -m scripts.demo_workflow samples/sample_form.pdf
make corpus-check
```
