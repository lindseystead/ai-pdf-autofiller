# Contributing

## Development Setup

1. Use Python 3.11 or 3.12.
2. Create and activate a virtual environment.
3. Install dependencies with `pip install -r requirements-dev.txt` or `poetry install`.

## Local Validation

Run the same core checks expected in CI before opening a pull request:

```bash
ruff check src/ tests/ scripts/
mypy src/
pip-audit -r requirements.txt
PYTHONPATH=src pytest tests/ -v --cov=src --cov-report=term --cov-fail-under=85
PYTHONPATH=src python -m scripts.verify_claims
```

`pip-audit` requires network access so it can query the vulnerability advisory service.

The helper targets in `Makefile` are the supported shortcuts for common local workflows.

## Code Standards

- Keep business logic in `src/`; keep scripts thin.
- Prefer deterministic behavior over implicit heuristics.
- Add or update tests for every behavioral change.
- Keep documentation in sync when changing APIs, configuration, or operational assumptions.
- Avoid mixing unrelated refactors with feature or bug-fix changes.

## Pull Requests

- Describe the problem being solved and the behavioral change.
- Call out any API contract changes, security implications, or deployment impact.
- Include the validation commands you ran locally.
- Update `CHANGELOG.md` when the change materially affects behavior, docs, or operations.
- Follow the [Code of Conduct](CODE_OF_CONDUCT.md).
