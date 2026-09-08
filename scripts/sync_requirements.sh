#!/usr/bin/env bash
# Export pinned requirements.txt / requirements-dev.txt from poetry.lock.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if ! command -v poetry >/dev/null 2>&1; then
  echo "poetry is required (pipx install poetry && poetry self add poetry-plugin-export)" >&2
  exit 1
fi

if ! poetry export -h >/dev/null 2>&1; then
  echo "Installing poetry-plugin-export…" >&2
  poetry self add poetry-plugin-export >/dev/null
fi

tmp_main="$(mktemp)"
tmp_dev="$(mktemp)"
trap 'rm -f "$tmp_main" "$tmp_dev"' EXIT

poetry export -f requirements.txt --only main --without-hashes -o "$tmp_main"
poetry export -f requirements.txt --with dev --without-hashes -o "$tmp_dev"

{
  echo "# Generated from poetry.lock — do not hand-edit."
  echo "# Regenerate: make sync-requirements"
  echo "# Source of truth: pyproject.toml + poetry.lock"
  echo
  cat "$tmp_main"
} > requirements.txt

{
  echo "# Generated from poetry.lock — do not hand-edit."
  echo "# Regenerate: make sync-requirements"
  echo "# Includes runtime + dev tools for CI/local parity."
  echo
  cat "$tmp_dev"
} > requirements-dev.txt

echo "Wrote requirements.txt and requirements-dev.txt from poetry.lock"
