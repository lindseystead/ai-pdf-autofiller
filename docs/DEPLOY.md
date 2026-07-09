# Render Blueprint — PDF Autofiller Playground

Deploy the public playground API on Render's free tier.

## One-click deploy

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy)

Or connect this repo manually using the settings below.

## Service settings

| Setting | Value |
|---------|-------|
| **Runtime** | Docker |
| **Plan** | Free |
| **Branch** | `main` |
| **Health check path** | `/health` |
| **Port** | `8000` |

## Required environment variables

| Key | Value | Notes |
|-----|-------|-------|
| `API_AUTH_ENABLED` | `false` | Playground needs unauthenticated fills on demo tier |
| `RATE_LIMIT_PER_MINUTE` | `30` | Protect free tier from abuse |
| `MAX_UPLOAD_BYTES` | `5242880` | 5 MB |
| `LOG_LEVEL` | `INFO` | |

## Optional

| Key | Value | Notes |
|-----|-------|-------|
| `MODEL_PROVIDER_API_KEY` | your key | Enables AI inference in playground |
| `API_AUTH_ENABLED` | `true` | Production — set strong `API_AUTH_TOKEN` |

## After deploy

- Playground: `https://<your-service>.onrender.com/playground`
- API docs: `https://<your-service>.onrender.com/docs`
- Health: `https://<your-service>.onrender.com/health`

Update README playground link once live.

## Post-release checklist

1. **PyPI** — add `PYPI_API_TOKEN` to GitHub secrets, re-run [Publish to PyPI](../.github/workflows/publish-pypi.yml). See [PUBLISH.md](PUBLISH.md).
2. **Render** — deploy blueprint above and paste live playground URL into README.
3. **Launch** — use copy in [LAUNCH.md](LAUNCH.md) once the public playground is up.

## render.yaml

This repo includes `render.yaml` for Blueprint deploys. Connect the repo in Render Dashboard → **New Blueprint**.
