# Contributing

## Development Setup

1. Use Python 3.11 or newer (CI tests 3.11 to 3.14).
2. Create and activate a virtual environment.
3. Install dependencies with `pip install -r requirements-dev.txt` or `poetry install`.

## Local Validation

Run the same core checks expected in CI before opening a pull request:

```bash
ruff check src/ tests/ scripts/ examples/
ruff format --check src/ tests/ scripts/ examples/
mypy src/
pip-audit -r requirements.txt
PYTHONPATH=src pytest tests/ -v --cov=src --cov-report=term --cov-fail-under=85
make corpus-check
```

Optional: `pre-commit install` then `pre-commit run --all-files` (Ruff + mypy).

`pip-audit` requires network access so it can query the vulnerability advisory service.

The helper targets in `Makefile` are the supported shortcuts for common local workflows.

## Code Standards

- Keep business logic in `src/`; keep scripts thin.
- Prefer deterministic behavior over implicit heuristics.
- Alias packs live only under `src/pdf_autofiller/form_aliases/`. To add one: create
  `<family>.json` there with canonical snake_case semantics as keys and lists of user-data key
  variants as values, and prove it with a synthetic case in `tests/fixtures/corpus/`. Do not
  claim success on a real IRS or vendor form without a redacted fixture. Deploy-time overrides
  (`FORM_ALIASES_DIR`) are described in `docs/OPERATIONS.md`.
- Add or update tests for every behavioral change; prove packs with corpus cases.
- Keep documentation in sync when changing APIs, configuration, or operational assumptions.
- Avoid mixing unrelated refactors with feature or bug-fix changes.
- Format with **Ruff only** (`make format`) — do not introduce a second formatter.
  CI runs `ruff format --check`, so unformatted code fails the build.

## Pull Requests

- Prefer **one focused commit per PR** (or squash before merge). This repo uses
  **squash merges** onto `main` so history stays linear.
- Write commit subjects in the imperative mood, ≤72 characters when possible
  (example: `Add date typing to the default fill path`).
- Put context in the body: what changed and why — not WIP notes, “fix typo”,
  or accidental artifact cleanups. Those belong in a rewritten local history
  before you push, not in the final squash message.
- Describe the problem being solved and the behavioral change in the PR body.
- Call out any API contract changes, security implications, or deployment impact.
- Include the validation commands you ran locally.
- Update `CHANGELOG.md` when the change materially affects behavior, docs, or operations.
- Follow the [Code of Conduct](CODE_OF_CONDUCT.md).
