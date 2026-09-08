# Alias packs live in the installable package — not this folder.
#
# Packs: `src/pdf_autofiller/form_aliases/*.json`
# Loader: `pdf_autofiller.aliases.AliasRegistry`
#
# This directory is intentionally empty of JSON so contributors do not add
# packs in two places. Contribution steps:

## Contribute a pack

1. Add `src/pdf_autofiller/form_aliases/<family>.json`
2. Keys = canonical semantic meanings (snake_case)
3. Values = arrays of user-data key variants
4. Add a synthetic corpus case under `tests/fixtures/corpus/` that proves the pack
5. Open a PR — do not claim real IRS/vendor form success without a redacted fixture

## Custom directory at deploy time

```bash
export FORM_ALIASES_DIR=/etc/pdf-autofiller/aliases
```

This **replaces** the packaged `form_aliases` directory (built-in code aliases in
`BUILTIN_ALIASES` still apply). Packs load when the default `AliasRegistry` is
first constructed; change the env var or JSON files and restart the process
(or call `set_default_registry(AliasRegistry.load())`).
