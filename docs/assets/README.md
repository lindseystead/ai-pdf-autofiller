# Repository assets

| File | Use | Regenerate |
|------|-----|------------|
| `social-preview.png` | GitHub social preview and README header | — |
| `playground-preview.png` | README screenshot of the playground after a fill | `python scripts/capture_playground_preview.py [base_url]` with the API running (needs Playwright) |
| `sample-filled.png` | README image of the filled sample form | Run the README Python example, then `pdftoppm -png -r 90 -singlefile -W 765 -H 400 filled.pdf docs/assets/sample-filled` |
| `demo-terminal.txt` | Example curl workflow output | `scripts/capture_demo_transcript.sh` with the API running |
