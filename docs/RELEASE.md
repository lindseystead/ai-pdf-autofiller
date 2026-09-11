# Releasing PDF Autofiller

Source of truth for versions: `pyproject.toml` + `src/pdf_autofiller/__init__.py` (keep equal).

**Supported install today:** GitHub Release wheels (`make install-release` /
[Releases](https://github.com/lindseystead/ai-pdf-autofiller/releases)), editable
install (`pip install -e .` → `pdf-autofiller` CLI), or Docker/GHCR.

**PyPI** (`pip install pdf-autofiller`) is **one click away** once a Trusted
Publisher is configured (see below). The publish workflow is **manual only** so
GitHub Releases stay green without that setup.

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

## Enabling PyPI (one-time, ~2 minutes — unlocks `pip install pdf-autofiller`)

This is the remaining human step. The workflow already exists; PyPI just needs
your account linked once.

1. Create / log into a [PyPI](https://pypi.org) account (use the same identity
   you want as package owner).
2. Open [Trusted Publishers → Add a new pending publisher](https://pypi.org/manage/account/publishing/)
   and fill:

   | Field | Value |
   |-------|--------|
   | PyPI project name | `pdf-autofiller` |
   | Owner | `lindseystead` |
   | Repository | `ai-pdf-autofiller` |
   | Workflow name | `publish-pypi.yml` |
   | Environment name | `pypi` |

3. In GitHub → **Settings → Environments**, create an environment named `pypi`
   (empty is fine; optional reviewers later).
4. From a green `main`, publish:

```bash
gh workflow run publish-pypi.yml --ref main
gh run watch   # wait until success
```

5. Confirm anyone can install:

```bash
pip install -U pdf-autofiller
pdf-autofiller version
```

6. Optionally re-add `on.release.types: [published]` to
   `.github/workflows/publish-pypi.yml` so future GitHub Releases also push to
   PyPI. Until then, leave it **manual** so a missing PyPI config cannot fail a
   Release.

**What this accomplishes:** strangers can `pip install pdf-autofiller` without
cloning the repo or hunting GitHub Release wheels — the main discovery path for
Python tools.

## Requirements sync

```bash
make sync-requirements
# commit requirements.txt + requirements-dev.txt with the lockfile
```

CI fails if those files drift from the lock.
