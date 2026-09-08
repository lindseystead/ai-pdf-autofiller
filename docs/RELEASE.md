# Releasing PDF Autofiller

Source of truth for versions: `pyproject.toml` + `src/pdf_autofiller/__init__.py` (keep equal).

**Rule:** do not push a release tag or publish a GitHub Release until CI on `main` is green **and** PyPI publish is known to work (secret present + workflow uses API token only). A red `Publish to PyPI` run means `pip install pdf-autofiller` still fails for users.

## Prerequisites (all required)

1. **Green CI on `main`** — Tests, lint, lockfile sync, and other required checks must be green.
2. **`PYPI_API_TOKEN` repository secret** — Create a PyPI API token with upload scope for project `pdf-autofiller` (or the account that owns it). Store it as `PYPI_API_TOKEN` under GitHub → Settings → Secrets and variables → Actions.
3. **Maintainer permission** to publish GitHub Releases and re-run Actions workflows.
4. **Version bump committed on `main`** — `pyproject.toml` and `__init__.py` already match the tag you will cut.

### How publish works

`.github/workflows/publish-pypi.yml` uploads with **`user: __token__` + `PYPI_API_TOKEN` only**.

It does **not** use Trusted Publishing (OIDC). Do not add `permissions: id-token: write` unless you have also configured a matching PyPI trusted publisher; otherwise the action fails with `invalid-publisher` and never falls back to the API token.

Other release workflows (GHCR, release assets) are independent; they can succeed while PyPI fails. Treat a red PyPI job as a failed release for installability.

## Preflight (before any tag)

```bash
# 1. main is clean and CI green
git checkout main && git pull
gh run list --branch main --limit 5

# 2. Confirm the secret exists (you need repo admin; values are never shown)
#    GitHub UI: Settings → Secrets → Actions → PYPI_API_TOKEN

# 3. Optional dry-run of the publish workflow on main (does not need a new tag).
#    Safe if skip-existing is enabled and the version is already on PyPI;
#    otherwise this uploads the version currently on the checked-out ref.
gh workflow run publish-pypi.yml --ref main
gh run list --workflow=publish-pypi.yml --limit 3
```

Only proceed to tagging after a successful publish dry-run **or** after you have verified the secret and that the workflow file on `main` is the token-only variant.

## Cut a release

```bash
# Tag must match pyproject version (example)
git tag -a v0.6.1 -m "pdf-autofiller 0.6.1"
git push origin v0.6.1

# Publish a GitHub Release from the tag (this triggers release workflows)
gh release create v0.6.1 --generate-notes
```

Publishing the Release triggers:

| Workflow | Effect |
|----------|--------|
| `publish-pypi.yml` | Build + upload to PyPI via API token |
| `publish-ghcr.yml` | Push Docker image to GHCR |
| `release-assets.yml` | Attach sdist/wheel to the Release |

### If PyPI fails after a Release

1. Fix the workflow and/or secret on `main` (merge a PR; do not push another broken tag).
2. Wait for CI green on `main`.
3. Retry without a new tag:

```bash
gh workflow run publish-pypi.yml --ref v0.6.1
# or re-run the failed job from the Actions UI
```

`skip-existing: true` allows safe retries if the version partially uploaded.

## Verify (must pass before calling the release done)

```bash
pip index versions pdf-autofiller
pip install -U pdf-autofiller==0.6.1   # use the released version
python -c "import pdf_autofiller; print(pdf_autofiller.__version__)"
docker pull ghcr.io/lindseystead/ai-pdf-autofiller:latest
```

If PyPI still 404s, the release is **not** complete for `pip install` even when GHCR and GitHub Release assets are green.

## Requirements sync

After changing `pyproject.toml` / `poetry.lock`:

```bash
make sync-requirements
# commit requirements.txt + requirements-dev.txt with the lockfile
```

CI fails if those files drift from the lock.
