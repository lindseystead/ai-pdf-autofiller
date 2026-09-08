#!/usr/bin/env bash
# Capture a deterministic inspect → preview → fill demo transcript for docs.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
OUT="${1:-docs/assets/demo-terminal.txt}"
BASE="${PDF_AUTOFILLER_BASE_URL:-http://127.0.0.1:8000}"

if ! curl -sf "$BASE/health" >/dev/null; then
  echo "API not reachable at $BASE — start with: API_AUTH_ENABLED=false make run-api" >&2
  exit 1
fi

{
  echo "\$ curl -s $BASE/health | jq '{status,version:.version,semantic:.checks.semantic_provider}'"
  curl -s "$BASE/health" | python3 -c "import sys,json; d=json.load(sys.stdin); print(json.dumps({'status':d['status'],'version':d['version'],'semantic':d['checks'].get('semantic_provider')}, indent=2))"
  echo
  echo "\$ curl -s -X POST $BASE/inspect -F pdf_file=@samples/sample_form.pdf | jq '{pages,field_count,fields:[.fields[].name]}'"
  curl -s -X POST "$BASE/inspect" -F "pdf_file=@samples/sample_form.pdf;type=application/pdf" \
    | python3 -c "import sys,json; d=json.load(sys.stdin); print(json.dumps({'pages':d['pages'],'field_count':d['field_count'],'fields':[f['name'] for f in d['fields']]}, indent=2))"
  echo
  echo "\$ curl -s -X POST $BASE/preview -F pdf_file=@samples/sample_form.pdf -F 'user_data={\"firstname\":\"Jane\",\"lastname\":\"Doe\",\"dob\":\"1990-01-01\"}' | jq '{decisions:[.decisions[]|{field_name,selected_value}],missing_required}'"
  curl -s -X POST "$BASE/preview" \
    -F "pdf_file=@samples/sample_form.pdf;type=application/pdf" \
    -F 'user_data={"firstname":"Jane","lastname":"Doe","dob":"1990-01-01"}' \
    | python3 -c "import sys,json; d=json.load(sys.stdin); print(json.dumps({'decisions':[{'field_name':x['field_name'],'selected_value':x['selected_value']} for x in d['decisions']],'missing_required':d['missing_required']}, indent=2))"
  echo
  echo "\$ curl -s -X POST $BASE/fill -F pdf_file=@samples/sample_form.pdf -F 'user_data={\"firstname\":\"Jane\",\"lastname\":\"Doe\",\"dob\":\"1990-01-01\"}' -o filled.pdf -D - -o /dev/null | grep -iE 'HTTP/|X-PDF|content-type'"
  curl -s -D - -o /tmp/pdf-autofiller-demo-filled.pdf -X POST "$BASE/fill" \
    -F "pdf_file=@samples/sample_form.pdf;type=application/pdf" \
    -F 'user_data={"firstname":"Jane","lastname":"Doe","dob":"1990-01-01"}' \
    | tr -d '\r' | grep -iE 'HTTP/|x-pdf|content-type' || true
  echo
  echo "filled.pdf written ($(wc -c </tmp/pdf-autofiller-demo-filled.pdf) bytes)"
} | tee "$OUT"

echo "Wrote $OUT"
