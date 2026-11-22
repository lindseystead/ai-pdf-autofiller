# Examples

| File | What it shows |
|------|---------------|
| [quickstart.py](quickstart.py) | Fill `samples/sample_form.pdf` from a Python dict with the local library (no server) |
| [batch_fill.py](batch_fill.py) | Fill that form once per person in [contractors.json](contractors.json) |

Run from the repository root after `pip install -e .`:

```bash
python examples/quickstart.py                 # → out/filled_sample.pdf
python examples/quickstart.py /tmp/filled.pdf # custom output path
python examples/batch_fill.py                   # → out/contractors/Doe.pdf, Lee.pdf
```

More end-to-end flows (curl, W-9-shaped, HR, opaque vendor forms) live in [recipes/](../recipes/).
