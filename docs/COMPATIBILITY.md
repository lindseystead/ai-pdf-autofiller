# Compatibility program

The supported input is an unlocked AcroForm PDF. Flat/scanned documents and XFA-only forms are
outside the current product boundary and should fail clearly rather than appear to succeed.

Run the public synthetic corpus:

```bash
PYTHONPATH=src python scripts/compatibility_report.py
```

The command fills each form deterministically, reopens the output, measures expected-field hit
rate, and writes a report containing counts and field identifiers—but never input values.

For operator-owned or licensed PDFs, copy `tests/fixtures/compatibility/private.example.json` to
an ignored location, put PDFs under `tests/fixtures/compatibility/private/`, and pass that manifest:

```bash
PYTHONPATH=src python scripts/compatibility_report.py \
  --manifest tests/fixtures/compatibility/private.json \
  --output-dir compatibility-output/private \
  --report compatibility-report.json
```

Never commit government forms whose redistribution terms are unclear, customer PDFs, completed
forms, real personal data, or generated outputs. Use synthetic values and keep evidence of the
operator's right to test each private document.

## Manual viewer matrix

Automated parsing cannot prove visible appearances. Before claiming compatibility for a template,
open one synthetic completed output in Adobe Acrobat Reader, Chrome or Edge, and macOS Preview when
supporting Mac users. Record whether text, checkboxes, radio buttons, choice fields, Unicode, long
values, and flattened outputs remain visible. A parseable PDF with invisible appearances is a failure.
