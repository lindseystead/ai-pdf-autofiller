# Sample PDFs

This directory contains sample PDF forms for testing the PDF autofiller.

## Files

- `sample_form.pdf` - Sample fillable form with common fields
- `sample_form_filled.pdf` - Generated output from the demo flow (gitignored)

## Usage

To test with the sample form:

```bash
PYTHONPATH=src python -m scripts.demo_workflow samples/sample_form.pdf
```
