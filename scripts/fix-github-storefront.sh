#!/usr/bin/env bash
# Run locally as a repo admin (your account, not the cloud agent token):
#   bash scripts/fix-github-storefront.sh
set -euo pipefail
REPO="${GITHUB_REPOSITORY:-lindseystead/ai-pdf-autofiller}"

gh api -X PATCH "repos/${REPO}" \
  -f description='Fill AcroForm PDFs from JSON — open-source FastAPI API with playground, Docker, and Python SDK.' \
  -f homepage=''

# Close stale polish / abandoned review PRs if still open
gh pr view 31 --json state -q .state 2>/dev/null | grep -q OPEN && gh pr close 31 -c "Superseded by v0.6.3 recruiter polish on main." || true
gh pr view 32 --json state -q .state 2>/dev/null | grep -q OPEN && gh pr close 32 -c "Stale — superseded by later hardening on main." || true

echo
echo "Manual (UI only):"
echo "  1. Settings → General → Social preview → upload docs/assets/social-preview.png"
echo "  2. Optional: Settings → Pages → Source = GitHub Actions, then set homepage to https://lindseystead.github.io/ai-pdf-autofiller/"
echo "Done. Verify: https://github.com/${REPO}"
