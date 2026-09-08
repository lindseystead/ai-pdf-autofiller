# Releasing PDF Autofiller

Source of truth for versions: `pyproject.toml` + `src/pdf_autofiller/__init__.py` (keep equal).

**Supported install today:** GitHub Release wheels (`make install-release` / [Releases](https://github.com/lindseystead/ai-pdf-autofiller/releases)), editable install, or Docker/GHCR.

**PyPI** (`pip install pdf-autofiller`) is **deferred** until a one-time Trusted Publisher is configured. The publish workflow is **manual only** so GitHub Releases stay green without that setup.

## Prerequisites for a GitHub Release

1. **Green CI on `main`**
2. **Version bump committed on `main`** — tag must match `pyproject.toml` / `__init__.py`
3. Maintainer permission to publish Releases

PyPI Trusted Publishing is **not** required to cut a Release.

## Cut a release

```bash
git checkout main && git pull
gh run list --branch main --limit 5   # confirm green

git tag -a v0.6.1 -m "pdf-autofiller 0.6.1"
git push origin v0.6.1
gh release create v0.6.1 --generate-notes
```

| Workflow | When | Effect |
|----------|------|--------|
| `release-assets.yml` | On Release | Attach sdist/wheel to the Release (primary pip install path) |
| `publish-ghcr.yml` | On Release | Push Docker image to GHCR |
| `publish-pypi.yml` | **Manual only** | Upload to PyPI via OIDC when you choose to enable it |

### Verify a Release (without PyPI)

```bash
make install-release
python -c "import pdf_autofiller; print(pdf_autofiller.__version__)"
docker pull ghcr.io/lindseystead/ai-pdf-autofiller:latest
```

## Enabling PyPI later (optional, ~2 minutes)

1. On [PyPI publishing](https://pypi.org/manage/account/publishing/), add a pending/trusted publisher:

   | Field | Value |
   |-------|--------|
   | PyPI project name | `pdf-autofiller` |
   | Owner | `lindseystead` |
   | Repository | `ai-pdf-autofiller` |
   | Workflow name | `publish-pypi.yml` |
   | Environment name | `pypi` |

2. Dispatch once from a green `main`:

```bash
gh workflow run publish-pypi.yml --ref main
```

3. Confirm:

```bash
pip install -U pdf-autofiller
```

4. Optionally re-add `on.release.types: [published]` to `.github/workflows/publish-pypi.yml` so future Releases also publish to PyPI. Until then, leave it manual so missing PyPI config cannot fail a Release.

## Requirements sync

```bash
make sync-requirements
# commit requirements.txt + requirements-dev.txt with the lockfile
```

CI fails if those files drift from the lock.
