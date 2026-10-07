# Examples

| File | What it shows |
|------|---------------|
| [quickstart.py](quickstart.py) | Fill `samples/sample_form.pdf` from a Python dict with the local library (no server) |

Run from the repository root after `pip install pdf-autofiller` (or `pip install -e .`):

```bash
python examples/quickstart.py                 # → out/filled_sample.pdf
python examples/quickstart.py /tmp/filled.pdf # custom output path
```

More end-to-end flows (curl, W-9-shaped, HR, opaque vendor forms) live in [recipes/](../recipes/).
