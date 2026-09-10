"""Capture playground screenshot for README docs/assets."""

from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path("docs/assets/playground-preview.png")
URL = "http://127.0.0.1:8000/playground"


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto(URL, wait_until="networkidle")
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
    main()
