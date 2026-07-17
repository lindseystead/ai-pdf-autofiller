#!/usr/bin/env python3
"""Record a live playground demo video for recruiter-facing README assets.

Prerequisites:
  - API running at http://127.0.0.1:8000 with API_AUTH_ENABLED=false
  - playwright + chromium installed (`pip install playwright && playwright install chromium`)
  - ffmpeg available on PATH

Outputs:
  - docs/assets/demo-playground.mp4
  - docs/assets/playground-preview.png (fresh still frame)
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SAMPLE_PDF = ROOT / "samples" / "sample_form.pdf"
OUT_MP4 = ROOT / "docs" / "assets" / "demo-playground.mp4"
OUT_PNG = ROOT / "docs" / "assets" / "playground-preview.png"
BASE_URL = "http://127.0.0.1:8000"


def _require_api() -> None:
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen(f"{BASE_URL}/health", timeout=3) as response:
            if response.status != 200:
                raise RuntimeError(f"/health returned {response.status}")
    except (urllib.error.URLError, TimeoutError) as exc:
        raise SystemExit(
            "API is not reachable at http://127.0.0.1:8000. "
            "Start it with: API_AUTH_ENABLED=false make run-api"
        ) from exc


def main() -> int:
    _require_api()
    if not SAMPLE_PDF.exists():
        raise SystemExit(f"Missing sample PDF: {SAMPLE_PDF}")

    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise SystemExit(
            "playwright is required. Install with: pip install playwright && playwright install chromium"
        ) from exc

    if shutil.which("ffmpeg") is None:
        raise SystemExit("ffmpeg is required on PATH to encode the demo MP4")

    OUT_MP4.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="pdf-autofiller-demo-") as tmp:
        tmp_path = Path(tmp)
        video_dir = tmp_path / "video"
        video_dir.mkdir()

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(
                viewport={"width": 1280, "height": 800},
                record_video_dir=str(video_dir),
                record_video_size={"width": 1280, "height": 800},
            )
            page = context.new_page()

            # Open health first so the recording shows a live service, then playground.
            page.goto(f"{BASE_URL}/health", wait_until="networkidle")
            page.wait_for_timeout(1800)

            page.goto(f"{BASE_URL}/playground", wait_until="networkidle")
            page.wait_for_timeout(2200)

            page.set_input_files("#file", str(SAMPLE_PDF))
            page.wait_for_timeout(1600)

            page.click("#sampleBtn")
            page.wait_for_timeout(1400)

            page.click("#fillBtn")
            page.wait_for_selector("#status.ok", timeout=15000)
            page.wait_for_timeout(2500)

            page.screenshot(path=str(OUT_PNG), full_page=True)
            page.wait_for_timeout(2200)

            page_video = page.video
            context.close()
            browser.close()

            if page_video is None:
                raise SystemExit("Playwright did not produce a video recording")
            webm_path = Path(page_video.path())
            # Give the browser a moment to flush the webm to disk.
            for _ in range(20):
                if webm_path.exists() and webm_path.stat().st_size > 0:
                    break
                time.sleep(0.25)
            if not webm_path.exists():
                raise SystemExit(f"Video file missing: {webm_path}")

            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-i",
                    str(webm_path),
                    "-c:v",
                    "libx264",
                    "-pix_fmt",
                    "yuv420p",
                    "-movflags",
                    "+faststart",
                    str(OUT_MP4),
                ],
                check=True,
                capture_output=True,
            )

    print(f"Wrote {OUT_MP4.relative_to(ROOT)} ({OUT_MP4.stat().st_size} bytes)")
    print(f"Wrote {OUT_PNG.relative_to(ROOT)} ({OUT_PNG.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
