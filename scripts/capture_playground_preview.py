"""Capture the playground screenshot used in the README (docs/assets/playground-preview.png).

Needs Playwright with Chromium (`pip install playwright && playwright install chromium`)
and a running API with auth off:

    API_AUTH_ENABLED=false pdf-autofiller-api
    python scripts/capture_playground_preview.py [http://127.0.0.1:8000]
"""

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path("docs/assets/playground-preview.png")


def main(base_url: str = "http://127.0.0.1:8000") -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto(f"{base_url}/playground", wait_until="networkidle")
        page.click("#loadSamplePdfBtn")
        page.wait_for_timeout(800)
        page.click("#fillBtn")
        page.wait_for_selector("#download", state="visible", timeout=20000)
        page.wait_for_timeout(500)
        OUT.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(OUT), full_page=True)
        browser.close()
    print(f"Wrote {OUT} ({OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main(*sys.argv[1:2])
