<div align="center">

<img src="docs/assets/social-preview.png" alt="PDF Autofiller — Fill AcroForm PDFs from JSON" width="800" />

# PDF Autofiller

**Fill PDF forms from JSON — as a Python library or a self-hosted API.**

Package and command name: `pdf-autofiller`.

Your data keys don't have to match the form's field names: `firstname` fills `txtFirstName`,
`first_name` or `First Name`. Every fill returns a report of what was written and what was left
blank. Runs locally with no AI and no network calls by default.

[![CI](https://github.com/lindseystead/ai-pdf-autofiller/actions/workflows/test.yml/badge.svg)](https://github.com/lindseystead/ai-pdf-autofiller/actions/workflows/test.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%20%7C%203.12-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

</div>

## Quickstart

```bash
pip install git+https://github.com/lindseystead/ai-pdf-autofiller.git
curl -LO https://raw.githubusercontent.com/lindseystead/ai-pdf-autofiller/main/samples/sample_form.pdf
```

```python
from pdf_autofiller import fill

report = fill("sample_form.pdf", {"firstname": "Jane", "lastname": "Doe", "dob": "1990-01-01"}, "filled.pdf")
print(report.written_fields)  # ['txtDOB', 'txtFirstName', 'txtLastName']
```

Fills are **strict** by default: if a required field can't be resolved, nothing is written and the
error lists what's missing. Pass `allow_partial=True` to write anyway and check
`report.missing_required_fields`.

The same thing from the command line:

```bash
pdf-autofiller fill sample_form.pdf --data '{"firstname":"Jane","lastname":"Doe","dob":"1990-01-01"}' -o filled.pdf
```

## Self-hosted API

Run it as a service so other apps, scripts or workflow tools (n8n, Zapier) can send a PDF and JSON
and get the filled PDF back:

```bash
docker run --rm -p 8000:8000 -e API_AUTH_ENABLED=false ghcr.io/lindseystead/ai-pdf-autofiller:latest
curl -F pdf_file=@sample_form.pdf -F 'user_data={"firstname":"Jane","lastname":"Doe","dob":"1990-01-01"}' \
  http://localhost:8000/fill -o filled.pdf
```

`API_AUTH_ENABLED=false` is for local use. In production, keep auth on and set `API_AUTH_TOKEN`;
clients send it as `X-API-Key`. See [docs/OPERATIONS.md](docs/OPERATIONS.md).

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/fill` | PDF + JSON in, filled PDF out |
| `POST` | `/preview` | Show how each field would be mapped, without writing |
| `POST` | `/inspect` | List the form's fields |
| `GET` | `/playground` | Test page for trying fills in the browser |
| `GET` | `/health`, `/version` | Health check and version |

Full contract and error codes: [docs/API.md](docs/API.md). A Python client is included:
`PDFAutofillerClient("http://localhost:8000", api_key="…").fill_to_file(...)`.

The server includes a small test page at `/playground` for trying fills without writing code:

<img src="docs/assets/playground-preview.png" alt="Playground: upload a PDF, paste JSON, download the filled PDF" width="700" />

## How matching works

1. Field names and your keys are normalized, so `First Name`, `first_name` and `txtFirstName`
   compare equal.
2. Built-in aliases cover common synonyms (`dob` / `date_of_birth`, `zip` / `postcode`), with
   optional packs for W-9-shaped and HR forms.
3. Anything left unmatched is reported, not guessed. Fields with opaque names (`field_12`) can be
   filled by their exact name, or mapped by an optional AI step. That step is off by default and
   only chooses which of your keys a field gets; it never writes values of its own.

Also handled: checkboxes, radio groups by option name, hierarchical field names
(`applicant.lastName`), nested JSON input and `/MaxLen` limits. Dates are written exactly as sent.

Works with fillable (AcroForm) PDFs. Scanned or flat PDFs have no form fields to fill.

## Alternatives

If you already know the exact field names, [pypdf](https://github.com/py-pdf/pypdf) (which this
project builds on) or [PyPDFForm](https://github.com/chinapandaman/PyPDFForm) are smaller
dependencies. Hosted services such as DocSpring or Anvil add visual template editors but run in
their cloud.

## More

- [Recipes](recipes/): W-9-shaped, HR onboarding and opaque-field examples, plus an importable
  [n8n workflow](docs/integrations/n8n-fill-workflow.json)
- [examples/quickstart.py](examples/quickstart.py): runnable example against `samples/`
- [FAQ](docs/FAQ.md) · [Architecture](docs/ARCHITECTURE.md) · [Security](SECURITY.md) ·
  [Changelog](CHANGELOG.md)

## Development

```bash
git clone https://github.com/lindseystead/ai-pdf-autofiller.git && cd ai-pdf-autofiller
pip install -r requirements-dev.txt && pip install -e .
make test lint
```

CI runs the tests on Python 3.11 and 3.12 with an 85% coverage floor. See
[CONTRIBUTING.md](CONTRIBUTING.md) and [docs/TESTING.md](docs/TESTING.md).

## License

MIT — [LICENSE](LICENSE)
