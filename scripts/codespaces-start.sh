#!/usr/bin/env bash
# Start the API for GitHub Codespaces (playground opens via port forward).
set -euo pipefail

export API_AUTH_ENABLED=false
export PYTHONPATH="${PYTHONPATH:-}:src"

if pgrep -f "uvicorn pdf_autofiller.api_service" >/dev/null 2>&1; then
  echo "PDF Autofiller API already running on port 8000"
  exit 0
fi

echo "Starting PDF Autofiller → http://localhost:8000/playground"
nohup python -m uvicorn pdf_autofiller.api_service:app \
  --host 0.0.0.0 \
  --port 8000 \
  > /tmp/pdf-autofiller.log 2>&1 &

sleep 2
if curl -sf http://127.0.0.1:8000/health >/dev/null; then
  echo "Ready. Open the Playground port or visit /playground"
else
  echo "Server starting… check /tmp/pdf-autofiller.log if /playground does not load."
fi
