# Releasing PDF Autofiller

Source of truth for versions: `pyproject.toml` + `src/pdf_autofiller/__init__.py` (keep equal).

## Prerequisites

1. `PYPI_API_TOKEN` GitHub Actions secret (PyPI API token with upload scope)
2. Maintainer permission to publish GitHub Releases
3. Green CI on `main`

## Cut a release (0.6.x or later)

```bash
# 1. Ensure main is clean and CI green
git checkout main && git pull

# 2. Tag matches pyproject version (example 0.6.0 already on main)
git tag -a v0.6.0 -m "pdf-autofiller 0.6.0"
git push origin v0.6.0

# 3. Publish a GitHub Release from the tag (UI or gh)
gh release create v0.6.0 --generate-notes
```

Publishing the Release triggers:

| Workflow | Effect |
|----------|--------|
| `publish-pypi.yml` | Build + Twine upload to PyPI |
| `publish-ghcr.yml` | Push Docker image to GHCR |
| `release-assets.yml` | Attach sdist/wheel to the Release |

Manual retry without a new tag:

```bash
gh workflow run publish-pypi.yml
gh workflow run publish-ghcr.yml
```

## Verify

```bash
pip install -U pdf-autofiller
python -c "import pdf_autofiller; print(pdf_autofiller.__version__)"
docker pull ghcr.io/lindseystead/ai-pdf-autofiller:latest
```

## Requirements sync

After changing `pyproject.toml` / `poetry.lock`:

```bash
make sync-requirements
# commit requirements.txt + requirements-dev.txt with the lockfile
```

CI fails if those files drift from the lock.
