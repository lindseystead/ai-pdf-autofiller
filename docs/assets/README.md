# Repository assets

| File | Use |
|------|-----|
| `social-preview.png` | GitHub social preview / README hero |
| `playground-preview.png` | README screenshot of the browser playground |
| `demo-playground.mp4` | Live browser demo of the playground fill flow |
| `demo-terminal.txt` | Example curl / SDK / demo_workflow output |

**GitHub social preview:** upload `social-preview.png` in **Settings → General → Social preview** (optional; README also displays it).

Regenerate the playground video (API must be running on port 8000):

```bash
API_AUTH_ENABLED=false make run-api
PYTHONPATH=src python -m scripts.record_demo
```
