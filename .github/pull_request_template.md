## Summary

- Describe the problem.
- Describe the behavioral change.

## Validation

- [ ] `ruff check src/ tests/ scripts/`
- [ ] `mypy src/`
- [ ] `pip-audit -r requirements.txt`
- [ ] `PYTHONPATH=src pytest tests/ -v --cov=src --cov-report=term --cov-fail-under=85`

## Review Notes

- [ ] API contract changed
- [ ] Documentation updated
- [ ] Security or data-handling impact noted
- [ ] Breaking change called out
