# Releasing PDF Autofiller

Source of truth for versions: `pyproject.toml` + `src/pdf_autofiller/__init__.py` (keep equal).

**Install paths:** PyPI (`pip install pdf-autofiller`), Docker/GHCR, GitHub
Release wheels (`make install-release`), or from source (`pip install -e .`).

Publishing a GitHub Release uploads to PyPI automatically via
`publish-pypi.yml` (Trusted Publishing; one-time setup below). The workflow can
also be run manually to retry.

## Prerequisites for a GitHub Release

1. **Green CI on `main`**
2. **Version bump committed on `main`** — tag must match `pyproject.toml` / `__init__.py`
3. Maintainer permission to publish Releases

4. PyPI Trusted Publisher configured (see below) — otherwise the
   `publish-pypi.yml` run for that Release fails (GHCR and wheels still ship).

## Cut a release

```bash
git checkout main && git pull
gh run list --branch main --limit 5   # confirm green

VERSION=X.Y.Z   # must match pyproject.toml and __init__.py
git tag -a "v$VERSION" -m "pdf-autofiller $VERSION"
git push origin "v$VERSION"
gh release create "v$VERSION" --generate-notes
```

| Workflow | When | Effect |
|----------|------|--------|
| `release-assets.yml` | On Release (or manual) | Attach sdist/wheel to the Release (primary pip install path) |
| `publish-ghcr.yml` | On Release (or manual) | Push Docker image to GHCR |
| `publish-pypi.yml` | On Release (or manual) | Upload sdist/wheel to PyPI via OIDC |

### Verify a Release (without PyPI)

```bash
make install-release
python -c "import pdf_autofiller; print(pdf_autofiller.__version__)"
docker pull ghcr.io/lindseystead/ai-pdf-autofiller:latest
```

## Enabling PyPI publishing (one-time setup)

The workflow already exists; PyPI needs a one-time Trusted Publisher link.

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

After that, every published GitHub Release pushes to PyPI automatically
(`on.release.types: [published]`); re-runs for an existing version are no-ops
(`skip-existing`).

**What this enables:** users can install with `pip install pdf-autofiller`
without cloning the repository or downloading Release wheels.

## Requirements sync

```bash
make sync-requirements
# commit requirements.txt + requirements-dev.txt with the lockfile
```

CI fails if those files drift from the lock.
