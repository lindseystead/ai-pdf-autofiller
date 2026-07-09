#!/usr/bin/env bash
# Run locally with your GitHub CLI (admin on the repo):
#   bash scripts/apply-repo-metadata.sh
set -euo pipefail

REPO="${GITHUB_REPOSITORY:-lindseystead/ai-pdf-autofiller}"

DESCRIPTION="Fill any AcroForm PDF from JSON — open-source API with playground, Docker, and Python SDK. No manual field mapping."

TOPICS='[
  "pdf",
  "pdf-forms",
  "acroform",
  "form-filling",
  "form-automation",
  "fastapi",
  "python",
  "api",
  "docker",
  "automation",
  "document-processing",
  "workflow-automation",
  "self-hosted",
  "open-source",
  "developer-tools",
  "govtech",
  "pydantic",
  "n8n",
  "zapier",
  "document-automation"
]'

echo "Updating description for ${REPO}..."
gh api -X PATCH "repos/${REPO}" -f description="${DESCRIPTION}"

echo "Updating topics for ${REPO}..."
gh api -X PUT "repos/${REPO}/topics" \
  --input - <<< "{\"names\": ${TOPICS}}"

echo "Done. Verify at https://github.com/${REPO}"
