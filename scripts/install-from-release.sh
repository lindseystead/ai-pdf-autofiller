#!/usr/bin/env bash
# Install pdf-autofiller from the latest GitHub Release wheel (no PyPI account needed).
set -euo pipefail

REPO="${PDF_AUTOFILLER_REPO:-lindseystead/ai-pdf-autofiller}"

json="$(curl -fsSL "https://api.github.com/repos/${REPO}/releases/latest")"
wheel_url="$(printf '%s' "$json" | python3 -c "
import json, sys
data = json.load(sys.stdin)
for asset in data.get('assets', []):
    name = asset.get('name', '')
    if name.endswith('.whl'):
        print(asset['browser_download_url'])
        break
else:
    sys.exit('No wheel found on latest release. Wait for the release-assets workflow or install from source.')
")"

echo "Installing from: $wheel_url"
python3 -m pip install --upgrade "$wheel_url"
python3 -c "from pdf_autofiller import __version__; print(f'Installed pdf-autofiller {__version__}')"
