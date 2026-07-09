# Publishing to PyPI

## Automatic publish (recommended)

1. Create a [PyPI account](https://pypi.org/account/register/) if needed.
2. Generate an API token: PyPI → Account settings → API tokens → scope to `pdf-autofiller` (or entire account for first publish).
3. Add the token to GitHub:
   - Repo → **Settings** → **Secrets and variables** → **Actions**
   - New secret: `PYPI_API_TOKEN`
4. Create a GitHub Release (tag `v0.4.0`, `v0.4.1`, …). The `Publish to PyPI` workflow runs automatically.

### Re-run a failed publish

Actions → **Publish to PyPI** → **Run workflow**, or re-publish the release.

## Manual publish (one-time)

```bash
pip install build twine
python -m build
twine upload dist/*
```

Use `TWINE_USERNAME=__token__` and `TWINE_PASSWORD=<pypi-api-token>`.

## Verify install

```bash
pip install pdf-autofiller
python -c "from pdf_autofiller import fill, __version__; print(__version__)"
```

## Optional: PyPI trusted publishing (OIDC)

Instead of an API token, you can configure [trusted publishing](https://docs.pypi.org/trusted-publishers/) on PyPI:

| Field | Value |
|-------|-------|
| Owner | `lindseystead` |
| Repository | `ai-pdf-autofiller` |
| Workflow | `publish-pypi.yml` |
| Environment | _(leave empty unless using GitHub Environment)_ |

Then remove `password` from the workflow and add `permissions: id-token: write`. The current workflow uses `PYPI_API_TOKEN` for simplicity.

## First-time package name

Ensure `pdf-autofiller` is available on PyPI. If taken, update `name` in `pyproject.toml` before the first release.
