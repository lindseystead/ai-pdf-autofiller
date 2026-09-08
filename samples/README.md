# Sample PDFs

Synthetic AcroForms for demos and the golden corpus. **Not** official IRS or vendor PDFs.

## Files

| File | Generator | Role |
|------|-----------|------|
| `sample_form.pdf` | `scripts/create_sample_form.py` | Demo name/contact fields |
| `hr_intake_sample.pdf` | `scripts/create_corpus_forms.py` | HR intake + checkbox |
| `w9_shaped_sample.pdf` | `scripts/create_corpus_forms.py` | W-9-shaped names + `w9.json` pack |
| `address_contact_sample.pdf` | `scripts/create_corpus_forms.py` | Address/email/phone aliases |
| `hr_hire_alias_sample.pdf` | `scripts/create_corpus_forms.py` | HR pack hire_date/manager synonyms |

Expectations: `tests/fixtures/corpus/cases.json` · report: `make corpus-check`

## Usage

```bash
PYTHONPATH=src python3 -m scripts.create_corpus_forms
PYTHONPATH=src python3 -m scripts.demo_workflow samples/sample_form.pdf
make corpus-check
```
