#!/usr/bin/env bash
# Fill the bundled sample form in one command.
set -euo pipefail

API_URL="${API_URL:-http://localhost:8000}"
PDF="${1:-samples/sample_form.pdf}"
OUT="${2:-samples/sample_form_filled.pdf}"

curl -s -X POST "${API_URL}/fill" \
  ${API_AUTH_TOKEN:+-H "X-API-Key: ${API_AUTH_TOKEN}"} \
  -F "pdf_file=@${PDF};type=application/pdf" \
  -F 'user_data={"firstname":"Jane","lastname":"Doe","dob":"1990-01-01","email":"jane@example.com"}' \
  -F "strict=true" \
  -o "${OUT}"

echo "Wrote ${OUT}"
wc -c < "${OUT}" | xargs echo "Bytes:"
