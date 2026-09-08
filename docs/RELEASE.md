# Releasing PDF Autofiller

Source of truth for versions: `pyproject.toml` + `src/pdf_autofiller/__init__.py` (keep equal).

**Rule:** do not push a release tag or publish a GitHub Release until CI on `main` is green **and** PyPI Trusted Publishing is configured (see below). A red `Publish to PyPI` run means `pip install pdf-autofiller` still fails for users.

## Prerequisites (all required)

1. **Green CI on `main`**
2. **PyPI Trusted Publisher** (no GitHub API token secret) — one-time setup on [PyPI publishing](https://pypi.org/manage/account/publishing/):

   | Field | Value |
   |-------|--------|
   | PyPI project name | `pdf-autofiller` |
   | Owner | `lindseystead` |
   | Repository | `ai-pdf-autofiller` |
   | Workflow name | `publish-pypi.yml` |
   | Environment name | `pypi` |

   Use a **pending publisher** if the project is not on PyPI yet; it becomes active on the first successful upload.

3. **GitHub Environment `pypi`** — already present on this repo; the workflow sets `environment: pypi` so OIDC claims match.
4. **Maintainer permission** to publish GitHub Releases.
5. **Version bump committed on `main`** — tag must match `pyproject.toml` / `__init__.py`.

### How publish works

`.github/workflows/publish-pypi.yml` uses **Trusted Publishing (OIDC)** only:

- `permissions.id-token: write`
- `environment: pypi`
- **no** `PYPI_API_TOKEN` / `password`

Do not pass an API token into the action while OIDC is enabled unless you intend token auth; the supported path for this repo is OIDC with environment `pypi`.

## Preflight (before any tag)

```bash
git checkout main && git pull
gh run list --branch main --limit 5

# Optional: dry-run publish from main (uploads the version on that ref)
gh workflow run publish-pypi.yml --ref main
gh run list --workflow=publish-pypi.yml --limit 3
```

Only proceed after a green publish dry-run, or after you have confirmed the PyPI trusted publisher fields above match the workflow.

## Cut a release

```bash
git tag -a v0.6.1 -m "pdf-autofiller 0.6.1"
git push origin v0.6.1
gh release create v0.6.1 --generate-notes
```

| Workflow | Effect |
|----------|--------|
| `publish-pypi.yml` | Build + upload to PyPI via OIDC (`environment: pypi`) |
| `publish-ghcr.yml` | Push Docker image to GHCR |
| `release-assets.yml` | Attach sdist/wheel to the Release |

### If PyPI fails after a Release

1. Confirm the PyPI trusted publisher row matches the table above (especially **Environment name = `pypi`**).
2. Ensure `main` has the OIDC workflow (`environment: pypi`, no API token).
3. Retry from a ref that includes that workflow:

```bash
gh workflow run publish-pypi.yml --ref main
```

Re-running an old release job pinned to a tag that lacked `environment: pypi` will keep failing. Prefer dispatch from `main`, or cut a new tag that includes the fixed workflow.

`skip-existing: true` allows safe retries if the version already uploaded.

## Verify (must pass before calling the release done)

```bash
pip index versions pdf-autofiller
pip install -U pdf-autofiller==0.6.1
python -c "import pdf_autofiller; print(pdf_autofiller.__version__)"
docker pull ghcr.io/lindseystead/ai-pdf-autofiller:latest
```

## Requirements sync

```bash
make sync-requirements
# commit requirements.txt + requirements-dev.txt with the lockfile
```

CI fails if those files drift from the lock.
