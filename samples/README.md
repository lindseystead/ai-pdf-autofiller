# Sample PDFs

This directory contains sample PDF forms for testing the PDF autofiller.

## Files

- `sample_form.pdf` — sample fillable form with common name/contact fields (`scripts/create_sample_form.py`)
- `hr_intake_sample.pdf` — synthetic HR intake AcroForm (`scripts/create_corpus_forms.py`)
- Corpus expectations: `tests/fixtures/corpus/cases.json`

## Usage

```bash
PYTHONPATH=src python3 -m scripts.demo_workflow samples/sample_form.pdf
make corpus-check
```
